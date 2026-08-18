"""Pluggable AI provider layer. One interface, two backends.

Swap providers per env (AI_PROVIDER=claude|openai) without changing call sites.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from django.conf import settings


class AIProviderError(RuntimeError):
    pass


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    raw: Optional[dict] = None

    def as_json(self) -> dict:
        """Parse `text` as JSON. Returns {} if the model didn't produce valid JSON."""
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return {}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    """One assistant turn from a chat call. Either it produced text, or it asked
    to run one or more tools (or both). The caller drives the tool loop."""
    text: str
    tool_calls: list  # list[ToolCall]
    provider: str
    model: str
    raw: Optional[dict] = None


class AIProvider:
    name = 'base'

    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> AIResponse:
        raise NotImplementedError

    def chat(self, messages: list, *, tools: Optional[list] = None,
             max_tokens: int = 1500) -> ChatResult:
        """Multi-turn chat with optional tool calling. ``messages`` follows the
        OpenAI chat schema (role/content, plus tool calls / tool results)."""
        raise NotImplementedError


class ClaudeProvider(AIProvider):
    name = 'claude'

    def __init__(self):
        if not settings.ANTHROPIC_API_KEY:
            raise AIProviderError(
                'ANTHROPIC_API_KEY is not configured. Set it in your .env file.'
            )
        try:
            import anthropic
        except ImportError as e:
            raise AIProviderError('anthropic package not installed. Run `pip install anthropic`.') from e
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.AI_MODEL_CLAUDE

    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> AIResponse:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[
                {
                    'type': 'text',
                    'text': system,
                    'cache_control': {'type': 'ephemeral'},
                }
            ],
            messages=[{'role': 'user', 'content': user}],
        )
        text = ''.join(block.text for block in msg.content if getattr(block, 'type', '') == 'text')
        return AIResponse(text=text, provider=self.name, model=self.model, raw=msg.model_dump())

    def chat(self, messages, *, tools=None, max_tokens=1500):
        # The AI Analyst tool loop is built on the OpenAI tool-calling contract.
        # Keep Claude for the structured `complete()` jobs; point chat at OpenAI.
        raise AIProviderError(
            'The AI Analyst uses OpenAI tool calling. Set AI_PROVIDER=openai and '
            'provide OPENAI_API_KEY in your .env to use the chat assistant.'
        )


class OpenAIProvider(AIProvider):
    name = 'openai'

    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise AIProviderError(
                'OPENAI_API_KEY is not configured. Set it in your .env file.'
            )
        try:
            from openai import OpenAI
        except ImportError as e:
            raise AIProviderError('openai package not installed. Run `pip install openai`.') from e
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.AI_MODEL_OPENAI

    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> AIResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            response_format={'type': 'json_object'},
        )
        text = resp.choices[0].message.content or ''
        return AIResponse(text=text, provider=self.name, model=self.model, raw=resp.model_dump())

    def chat(self, messages, *, tools=None, max_tokens=1500):
        kwargs = {
            'model': self.model,
            'max_tokens': max_tokens,
            'messages': messages,
        }
        if tools:
            kwargs['tools'] = tools
            kwargs['tool_choice'] = 'auto'
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or '{}')
            except (ValueError, TypeError):
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return ChatResult(
            text=msg.content or '', tool_calls=calls,
            provider=self.name, model=self.model, raw=resp.model_dump(),
        )


_REGISTRY = {
    'claude': ClaudeProvider,
    'openai': OpenAIProvider,
}


def get_provider(name: Optional[str] = None) -> AIProvider:
    key = (name or settings.AI_PROVIDER or 'claude').lower()
    if key not in _REGISTRY:
        raise AIProviderError(f'Unknown AI provider: {key}. Choose claude or openai.')
    return _REGISTRY[key]()
