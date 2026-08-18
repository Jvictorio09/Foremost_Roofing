"""AI Analyst orchestrator.

Read-only, conversational, grounded on live ERP data via tool calls. The model
never sees a static data dump; it asks for exactly the slices it needs each turn
(so brand-new records are always reflected), then answers in plain language.
"""
from __future__ import annotations

import json

from django.utils import timezone

from . import tools
from .providers import get_provider

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are the AI Analyst for Foremost EG Manufacturing, a steel \
roofing manufacturer. You help management understand and forecast the business \
using the company's live ERP data.

Rules:
- You are READ-ONLY. You never create, edit, approve, or delete anything. If asked \
to change data, explain that you can only analyse and forecast.
- Ground every number in the tools. NEVER invent or guess figures. If you are \
unsure what data exists, call schema_overview first.
- Currency is Philippine peso (PHP). Production volume is measured in linear \
metres (LM). Steel gauges are in mm.
- The forecast returned by the tools is a linear (least-squares) trend baseline. \
When you forecast, cite it, then add judgement: call out seasonality, pipeline, \
open job orders, receivables risk, or capacity that could move the number. Be \
explicit that projections are estimates.
- Be concise and specific. Prefer short paragraphs and tight bullet lists. Quote \
the actual numbers you used and the year they cover.
- Today's date is {today}.
"""


def _system_message() -> dict:
    return {'role': 'system',
            'content': SYSTEM_PROMPT.format(today=timezone.localdate().isoformat())}


def ask(question: str, history=None, user=None, provider_name=None) -> dict:
    """Answer one question with tool-grounded reasoning.

    ``history`` is a list of prior turns [{'role': 'user'|'assistant',
    'content': str}]. Returns a dict: {text, tools_used, chart}.
    """
    provider = get_provider(provider_name)

    messages = [_system_message()]
    for turn in (history or []):
        role = turn.get('role')
        if role in ('user', 'assistant') and turn.get('content'):
            messages.append({'role': role, 'content': turn['content']})
    messages.append({'role': 'user', 'content': question})

    tools_used = []
    chart = None
    final_text = ''

    for _ in range(MAX_TOOL_ROUNDS):
        result = provider.chat(messages, tools=tools.TOOL_SPECS)
        if not result.tool_calls:
            final_text = result.text
            break

        # Re-append the assistant's tool-call message verbatim, then answer each
        # tool call with its live result.
        assistant_msg = result.raw['choices'][0]['message']
        messages.append(assistant_msg)
        for call in result.tool_calls:
            data = tools.run_tool(call.name, call.arguments, user=user)
            tools_used.append({'name': call.name, 'arguments': call.arguments})
            if isinstance(data, dict) and data.get('chart') and chart is None:
                chart = data['chart']
            messages.append({
                'role': 'tool',
                'tool_call_id': call.id,
                'content': json.dumps(data, default=str),
            })
    else:
        # Ran out of tool rounds without a final answer; ask for a plain summary.
        messages.append({
            'role': 'user',
            'content': 'Summarise your findings now in plain language, no more tools.',
        })
        final_text = provider.chat(messages).text

    return {
        'text': final_text or "I couldn't produce an answer. Please try rephrasing.",
        'tools_used': tools_used,
        'chart': chart,
    }
