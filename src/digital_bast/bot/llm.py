"""Optional Ollama-backed interpreter for the WhatsApp bot (docs/bast-e2e-plan.md §3.5).

`BOT_LLM_URL` unset -> this module is never called; `parse_command()` alone drives the
bot. When set, `LlmInterpreter.interpret()` is the *primary* interpreter and
`parse_command()` only runs as its fallback on any failure -- timeout, non-JSON,
schema violation, or an out-of-range period. That ordering is deliberate: a regex
match can silently be *wrong* (e.g. parsing the day "20" out of the year "2026"),
and only a fallback that runs after the LLM can catch that class of error; a
fallback that only triggers on regex UNKNOWN never sees it.

The model never computes a business value and never sees database contents --
only the user's message and today's date, or (for `choose_index`) a bounded
numbered list the caller already restricted to the sender's own candidates.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 -- pydantic needs this resolvable at runtime
from typing import Final, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from digital_bast.bot.whatsapp import BotCommand, Intent
from digital_bast.domain.completion import DateRange

_TIMEOUT_SECONDS: Final = 10.0
_MAX_SPAN_DAYS: Final = 366
_PERIOD_INTENTS: Final = frozenset(
    {
        Intent.COMPLETION_STATUS,
        Intent.EVIDENCE_RESUME,
        Intent.EXPORT_ATTENDANCE,
        Intent.GENERATE_BAST,
    }
)

_COMMAND_SYSTEM_PROMPT: Final = (
    "Kamu mengurai satu pesan WhatsApp menjadi perintah untuk sistem BAST. "
    "Balas HANYA satu objek JSON, tanpa teks lain, sesuai skema:\n"
    '{"intent": "completion-status|evidence-resume|export-attendance|generate-bast|'
    'system-status|unsupported-mutation|unknown", '
    '"start_date": "YYYY-MM-DD atau null", "end_date": "YYYY-MM-DD atau null", '
    '"report_type": "developer atau shifting atau null"}\n'
    "Gunakan unsupported-mutation untuk perintah yang mengubah sistem "
    "(restart, matikan, nyalakan, dsb). Gunakan system-status untuk pertanyaan status "
    "server/docker. export-attendance wajib mengisi report_type. Lengkapi tanggal/tahun "
    "yang tidak disebutkan eksplisit memakai tanggal hari ini yang diberikan di pesan user.\n"
    "Jika pesan menyebut dua tanggal, dipisah kata apa pun seperti 'sampai', 'sampe', "
    "'s/d', 'hingga', atau tanda '-', tanggal pertama yang disebut adalah start_date dan "
    "tanggal kedua adalah end_date -- jangan pernah mengganti salah satunya dengan "
    "tanggal hari ini selama kedua tanggal itu disebutkan eksplisit di pesan. Contoh: "
    'pesan "export attendance developer 5 juni - 10 juni" -> '
    '{"intent":"export-attendance","start_date":"2026-06-05","end_date":"2026-06-10",'
    '"report_type":"developer"}. Tanggal hari ini hanya dipakai untuk melengkapi bagian '
    "yang benar-benar tidak disebutkan (mis. tahun, atau saat hanya satu tanggal/nama "
    "bulan yang ada)."
)
_CHOICE_SYSTEM_PROMPT: Final = (
    "Pilih satu nomor dari daftar bernomor yang diberikan berdasarkan pesan user. "
    'Balas HANYA JSON {"choice": <angka 1..N>} atau {"choice": null} jika tidak yakin '
    "atau tidak ada yang cocok."
)


class BotCommandDraft(BaseModel):
    intent: Literal[
        "completion-status",
        "evidence-resume",
        "export-attendance",
        "generate-bast",
        "system-status",
        "unsupported-mutation",
        "unknown",
    ]
    start_date: date | None = None
    end_date: date | None = None
    report_type: Literal["developer", "shifting"] | None = None


class _ChoiceDraft(BaseModel):
    choice: int | None = Field(default=None)


class _ChatMessage(BaseModel):
    content: str = ""


class _ChatResponse(BaseModel):
    message: _ChatMessage = Field(default_factory=_ChatMessage)


def _validate_command(draft: BotCommandDraft) -> BotCommand | None:
    intent = Intent(draft.intent)
    if intent not in _PERIOD_INTENTS:
        return BotCommand(intent)
    if draft.start_date is None or draft.end_date is None:
        return None
    if draft.end_date < draft.start_date:
        return None
    if (draft.end_date - draft.start_date).days > _MAX_SPAN_DAYS:
        return None
    if intent is Intent.EXPORT_ATTENDANCE and draft.report_type is None:
        return None
    return BotCommand(
        intent, DateRange(draft.start_date, draft.end_date), report_type=draft.report_type
    )


class LlmInterpreter:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url: str = base_url
        self._model: str = model

    async def _chat_json(self, system_prompt: str, user_message: str) -> str | None:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=_TIMEOUT_SECONDS
            ) as client:
                response = await client.post("/api/chat", json=payload)
                _ = response.raise_for_status()
                parsed = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None
        return parsed.message.content or None

    async def interpret(self, text: str, today: date) -> BotCommand | None:
        content = await self._chat_json(
            _COMMAND_SYSTEM_PROMPT, f"Hari ini: {today.isoformat()}. Pesan: {text}"
        )
        if content is None:
            return None
        try:
            draft = BotCommandDraft.model_validate_json(content)
        except ValidationError:
            return None
        return _validate_command(draft)

    async def choose_index(self, candidates: tuple[str, ...], message: str) -> int | None:
        listing = "\n".join(
            f"{index}. {title}" for index, title in enumerate(candidates, start=1)
        )
        user_message = f"Daftar:\n{listing}\nPesan: {message}"
        content = await self._chat_json(_CHOICE_SYSTEM_PROMPT, user_message)
        if content is None:
            return None
        try:
            draft = _ChoiceDraft.model_validate_json(content)
        except ValidationError:
            return None
        if draft.choice is None or not (1 <= draft.choice <= len(candidates)):
            return None
        return draft.choice
