from __future__ import annotations

from typing import final

import httpx
from pydantic import BaseModel, Field, ValidationError


class _ChatMessage(BaseModel):
    content: str = ""


class _ChatChoice(BaseModel):
    message: _ChatMessage = Field(default_factory=_ChatMessage)


class _ChatResponse(BaseModel):
    choices: list[_ChatChoice] = Field(default_factory=list)


@final
class GroqChatClient:
    """TalentOpsChatClient backed by Groq's OpenAI-compatible chat API.

    Groq's LPU inference is fast enough that the generous timeout Ollama
    needs on this CPU-only box is unnecessary here -- kept well under
    nginx's proxy_read_timeout regardless, same as Ollama's client.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str | None:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    "/chat/completions",
                    json=payload,
                    headers=headers,
                )
                _ = response.raise_for_status()
                parsed = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None
        if not parsed.choices:
            return None
        content = parsed.choices[0].message.content.strip()
        return content or None
