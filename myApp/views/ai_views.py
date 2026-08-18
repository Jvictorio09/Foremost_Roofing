"""AI Analyst -- full-page, read-only conversational assistant.

Threads are private to their owner. Every answer is grounded on live ERP data
through the read-only tools in ``myApp.ai`` (no static data dump), so newly added
records are reflected on the next question.
"""
import time

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..ai import assistant
from ..ai.providers import AIProviderError
from ..models import AIConversation, AIMessage
from ..rbac import permission_required
from ..services import log_event
from .common import is_hx

HISTORY_TURNS = 20          # prior turns sent as context
MIN_SECONDS_BETWEEN = 1.0   # basic double-submit guard

STARTERS = [
    "Project this year's invoiced sales and explain the drivers.",
    'Forecast production output (LM) for the rest of the year by profile.',
    'Which coils are low or short on stock right now?',
    'Show accounts receivable aging and the biggest overdue customers.',
]


def _threads(user):
    return AIConversation.objects.filter(user=user)


def _provider_warning():
    """A friendly setup message when the AI provider isn't configured, so the
    page explains itself instead of only failing on the first question."""
    provider = (settings.AI_PROVIDER or 'claude').lower()
    if provider != 'openai':
        return ('The AI Analyst runs on OpenAI. Set AI_PROVIDER=openai and add your '
                'OPENAI_API_KEY in the .env file, then restart the server.')
    if not settings.OPENAI_API_KEY:
        return ('OPENAI_API_KEY is not set. Add it to your .env file and restart the '
                'server to enable the AI Analyst.')
    return None


def _history(conversation):
    msgs = (conversation.messages
            .filter(role__in=[AIMessage.Role.USER, AIMessage.Role.ASSISTANT])
            .order_by('created_at'))
    turns = [{'role': m.role, 'content': m.content} for m in msgs]
    return turns[-HISTORY_TURNS:]


@permission_required('ai.chat')
def ai_analyst(request):
    threads = _threads(request.user)
    active = threads.first()
    if active is None:
        # Always give the user a live thread so the composer works immediately.
        active = AIConversation.objects.create(user=request.user)
        threads = _threads(request.user)
    return render(request, 'ai/analyst.html', {
        'threads': threads, 'active': active,
        'messages': active.messages.all(),
        'starters': STARTERS,
        'ai_warning': _provider_warning(),
    })


@permission_required('ai.chat')
@require_POST
def ai_conversation_create(request):
    convo = AIConversation.objects.create(user=request.user)
    return redirect('ai_conversation', pk=convo.pk)


@permission_required('ai.chat')
def ai_conversation(request, pk):
    convo = get_object_or_404(AIConversation, pk=pk, user=request.user)
    threads = _threads(request.user)
    ctx = {
        'threads': threads, 'active': convo,
        'messages': convo.messages.all(), 'starters': STARTERS,
    }
    if is_hx(request):
        return render(request, 'ai/_conversation.html', ctx)
    return render(request, 'ai/analyst.html', ctx)


@permission_required('ai.chat')
@require_POST
def ai_message_send(request, pk):
    convo = get_object_or_404(AIConversation, pk=pk, user=request.user)
    question = (request.POST.get('message') or '').strip()
    if not question:
        return render(request, 'ai/_turn.html', {'user_msg': None, 'assistant_msg': None})

    # Basic double-submit guard: ignore a near-instant repeat of the last question.
    last = convo.messages.filter(role=AIMessage.Role.USER).order_by('-created_at').first()
    if (last and last.content == question
            and (timezone.now() - last.created_at).total_seconds() < MIN_SECONDS_BETWEEN):
        return render(request, 'ai/_turn.html', {'user_msg': last, 'assistant_msg': None})

    history = _history(convo)
    user_msg = AIMessage.objects.create(
        conversation=convo, role=AIMessage.Role.USER, content=question)

    started = time.monotonic()
    error = None
    try:
        result = assistant.ask(question, history=history, user=request.user)
        text = result['text']
        meta = {'tools_used': result.get('tools_used'), 'chart': result.get('chart')}
    except AIProviderError as e:
        text = f'The AI service is not available: {e}'
        meta = {'error': True}
        error = str(e)
    except Exception as e:  # noqa: BLE001 - never 500 the chat on a model hiccup
        text = ('Something went wrong answering that. Please try again or rephrase '
                f'your question. ({e})')
        meta = {'error': True}
        error = str(e)

    assistant_msg = AIMessage.objects.create(
        conversation=convo, role=AIMessage.Role.ASSISTANT, content=text, meta=meta)

    # Auto-title from the first question.
    if convo.title == 'New conversation':
        convo.title = question[:60] + ('...' if len(question) > 60 else '')
    convo.save(update_fields=['title', 'updated_at'])

    log_event(convo, 'ai.ask', actor=request.user, new={
        'tools': [t['name'] for t in (meta.get('tools_used') or [])],
        'latency_ms': int((time.monotonic() - started) * 1000),
        'error': error,
    })

    return render(request, 'ai/_turn.html', {
        'user_msg': user_msg, 'assistant_msg': assistant_msg, 'convo': convo,
    })


@permission_required('ai.chat')
@require_POST
def ai_conversation_delete(request, pk):
    convo = get_object_or_404(AIConversation, pk=pk, user=request.user)
    convo.delete()
    return redirect('ai_analyst')
