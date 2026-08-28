from __future__ import annotations

from typing import final

import httpx
from pydantic import BaseModel, Field, ValidationError


class _ChatMessage(BaseModel):
    content: str = ""


class _ChatChoice(BaseModel):
    message: _ChatMessage = Field(default_factory=_ChatMessage)


class _ChatResult(BaseModel):
    choices: list[_ChatChoice] = Field(default_factory=list)


class _ChatResponse(BaseModel):
    success: bool = False
    result: _ChatResult = Field(default_factory=_ChatResult)


@final
class CloudflareWorkersAiChatClient:
    """TalentOpsChatClient backed by Cloudflare Workers AI.

    Chosen over Groq for TalentOps investigation prompts specifically: a
    real command-center + evidence-catalog prompt runs ~11k tokens, which
    Groq's free-tier openai/gpt-oss-20b rejects outright (413, 8k TPM cap
    per request, not just per minute of use). Workers AI's free daily
    neuron pool and 32k context on qwen3-30b-a3b-fp8 has room for it --
    confirmed against the real prompt (10.7s, valid response).
    """

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
        self._api_token = api_token
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str | None:
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_token}"}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(f"/{self._model}", json=payload, headers=headers)
                _ = response.raise_for_status()
                parsed = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None
        if not parsed.success or not parsed.result.choices:
            return None
        content = parsed.result.choices[0].message.content.strip()
        return content or None
