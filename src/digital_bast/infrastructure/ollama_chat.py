from __future__ import annotations

from typing import final

import httpx
from pydantic import BaseModel, Field, ValidationError


class _ChatMessage(BaseModel):
    content: str = ""


class _ChatResponse(BaseModel):
    message: _ChatMessage = Field(default_factory=_ChatMessage)


@final
class OllamaChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 25.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
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
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post("/api/chat", json=payload)
                _ = response.raise_for_status()
                parsed = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None
        content = parsed.message.content.strip()
        return content or None
