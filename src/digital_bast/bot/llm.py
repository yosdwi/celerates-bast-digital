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
from pydantic import BaseModel, Field, ValidationError, field_validator

from digital_bast.bot.whatsapp import PERSONA_CAPABILITIES, PERSONA_NAME, BotCommand, Intent
from digital_bast.domain.completion import DateRange

_TIMEOUT_SECONDS: Final = 18.0
# Free-text persona generation runs noticeably longer than the short JSON
# classification above on this hardware (observed ~15-20s vs ~10-12s) --
# output length drives latency here, not prompt length.
_PERSONA_TIMEOUT_SECONDS: Final = 25.0
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
    'system-status|unsupported-mutation|conversation|unknown", '
    '"start_date": "YYYY-MM-DD atau null", "end_date": "YYYY-MM-DD atau null", '
    '"report_type": "developer atau shifting atau null", '
    '"employee": "nama talent yang ditanyakan secara spesifik, atau null"}\n'
    "Gunakan conversation HANYA untuk sapaan, perkenalan, pertanyaan identitas/kemampuan "
    "bot, ucapan terima kasih, atau obrolan ringan yang TIDAK meminta data atau aksi "
    "apa pun. Begitu pesan menyebut kata seperti status, evidence, task, export, "
    "attendance, generate, bast, sistem/server/docker, ATAU meminta data/tindakan apa "
    "pun -- walaupun disampaikan santai/pakai basa-basi -- JANGAN pakai conversation, "
    'pakai intent bisnis yang sesuai. Contoh: "kenalin dong siapa nih" -> '
    'conversation. "makasih ya" -> conversation. "bisa ngapain aja" -> conversation. '
    '"status bast agustus" -> completion-status (BUKAN conversation).\n'
    "Gunakan unsupported-mutation untuk perintah yang mengubah sistem "
    "(restart, matikan, nyalakan, dsb). Gunakan system-status HANYA jika pesan secara "
    "eksplisit menyebut server/container/docker/database/infrastruktur -- kata 'status' "
    "SENDIRIAN, atau 'status bast', atau 'status' + nama bulan/rentang tanggal, SELALU "
    "berarti completion-status (status kelengkapan dokumen BAST talent), BUKAN "
    'system-status. Contoh: pesan "liat status bast dong bulan agustus ini" -> '
    '{"intent":"completion-status",...}, BUKAN system-status. export-attendance wajib '
    "mengisi report_type. Lengkapi tanggal/tahun yang tidak disebutkan eksplisit memakai "
    "tanggal hari ini yang diberikan di pesan user.\n"
    "Jika pesan menyebut dua tanggal, dipisah kata apa pun seperti 'sampai', 'sampe', "
    "'s/d', 'hingga', atau tanda '-', tanggal pertama yang disebut adalah start_date dan "
    "tanggal kedua adalah end_date -- jangan pernah mengganti salah satunya dengan "
    "tanggal hari ini selama kedua tanggal itu disebutkan eksplisit di pesan. Contoh: "
    'pesan "export attendance developer 5 juni - 10 juni" -> '
    '{"intent":"export-attendance","start_date":"2026-06-05","end_date":"2026-06-10",'
    '"report_type":"developer"}. Tanggal hari ini hanya dipakai untuk melengkapi bagian '
    "yang benar-benar tidak disebutkan (mis. tahun, atau saat hanya satu tanggal/nama "
    "bulan yang ada).\n"
    "Isi employee HANYA jika pesan menanyakan status satu talent tertentu (mis. "
    '"kenapa yoses belum lengkap agustus?", "detail yoses agustus", "yoses kurang apa?" '
    '-> employee="yoses", intent="completion-status"). Untuk pertanyaan status umum/grup '
    '("status bast agustus", "siapa yang evidence-nya kurang") biarkan employee null.'
)
_CHOICE_SYSTEM_PROMPT: Final = (
    "Pilih satu nomor dari daftar bernomor yang diberikan berdasarkan pesan user. "
    'Balas HANYA JSON {"choice": <angka 1..N>} atau {"choice": null} jika tidak yakin '
    "atau tidak ada yang cocok."
)
_PERSONA_FACTS: Final = "\n".join(f"- {fact}" for fact in PERSONA_CAPABILITIES)
# Deliberately its own short, non-JSON call: keeping this out of
# _COMMAND_SYSTEM_PROMPT keeps every business-intent classification call fast
# (~10s) -- a "reply" field on that shared schema made the model generate a
# full sentence for it on every call regardless of intent, close to doubling
# latency across the board for a field only conversation ever uses.
_PERSONA_SYSTEM_PROMPT: Final = (
    f"Kamu adalah {PERSONA_NAME}, asisten otomatis untuk sistem Digital BAST, "
    "membalas pesan di grup WhatsApp kerja. Jawab HANYA berdasarkan daftar "
    "kemampuan berikut -- jangan mengarang fitur lain atau menjanjikan aksi di "
    f"luar daftar ini:\n{_PERSONA_FACTS}\n"
    "Gaya bahasa Indonesia sehari-hari yang santai dan hangat, seperti rekan "
    "kerja ngobrol biasa di grup WhatsApp -- BUKAN bahasa formal/korporat "
    '(hindari frasa kaku seperti "siap membantu dalam kerja sama" atau "demi '
    'kelancaran operasional"). Ringkas (2-5 kalimat mengalir, boleh beberapa '
    "baris pendek, tidak perlu bullet list), emoji secukupnya boleh. Jangan "
    f"berpura-pura jadi manusia -- {PERSONA_NAME} adalah bot/asisten otomatis, "
    "tapi tetap boleh terdengar hangat dan ramah, bukan kaku. Kalau menutup "
    "dengan ajakan, ajak user untuk tanya/chat langsung secara natural -- "
    'JANGAN pakai frasa "nggak perlu hafal command" (itu bukan cara pakainya, '
    "ini bukan aplikasi command-line). Balas HANYA teks natural untuk "
    "dikirim langsung ke WhatsApp, tanpa JSON."
)


class BotCommandDraft(BaseModel):
    intent: Literal[
        "completion-status",
        "evidence-resume",
        "export-attendance",
        "generate-bast",
        "system-status",
        "unsupported-mutation",
        "conversation",
        "unknown",
    ]
    start_date: date | None = None
    end_date: date | None = None
    report_type: Literal["developer", "shifting"] | None = None
    employee: str | None = None

    @field_validator("start_date", "end_date", "report_type", "employee", mode="before")
    @classmethod
    def _blank_string_is_none(cls, value: object) -> object:
        # The small local model occasionally emits the JSON string "null"
        # (or "none"/"") instead of a bare null -- that would otherwise fail
        # date/enum parsing and reject the whole draft, losing every other
        # field (report_type, employee) it got right.
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", ""}:
            return None
        return value


# DM's own deterministic keyword fast-paths (cli.py's _SUMMARY_WORDS /
# _ATTENDANCE_SUMMARY_WORDS) already cover the common, literal phrasings at
# zero latency -- this only runs as a last-resort fallback, after those and
# after _dm_llm_pick's task-title match both come up empty, for messages
# like "yang belum closed apa" or "clock in aku yang belum lengkap" that
# never contain the literal trigger words. Its own short schema/prompt for
# the same reason _PERSONA_SYSTEM_PROMPT is separate: a shared schema would
# slow down every other call for a field only this path needs.
_DM_INTENT_SYSTEM_PROMPT: Final = (
    "Kamu mengklasifikasi satu pesan WhatsApp dari chat pribadi (DM) seorang talent ke "
    "sistem Digital BAST. Balas HANYA satu objek JSON, tanpa teks lain, sesuai skema:\n"
    '{"intent": "tasklist|attendance|unknown"}\n'
    '"tasklist" untuk pertanyaan soal Task List/Evidence milik PENGIRIM SENDIRI: task mana '
    "yang belum Closed, task mana yang belum ada evidence, progress task list pribadi. "
    '"attendance" untuk pertanyaan soal Attendance/kehadiran milik PENGIRIM SENDIRI: hari '
    "mana yang clock in/out-nya belum lengkap, hari mana yang butuh evidence attendance. "
    '"unknown" kalau pesan tidak berkaitan dengan keduanya (basa-basi, pertanyaan lain, '
    "menanyakan orang lain, dsb).\n"
    'Contoh: "yang belum closed apa aja" -> {"intent":"tasklist"}. '
    '"evidence yang kurang apa" -> {"intent":"tasklist"}. '
    '"clock in aku yang belum lengkap yang mana" -> {"intent":"attendance"}. '
    '"absensi aku gimana" -> {"intent":"attendance"}.'
)


class _DmIntentDraft(BaseModel):
    intent: Literal["tasklist", "attendance", "unknown"]


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
    employee = None
    if intent is Intent.COMPLETION_STATUS and draft.employee:
        employee = draft.employee.strip()
    return BotCommand(
        intent,
        DateRange(draft.start_date, draft.end_date),
        employee=employee or None,
        report_type=draft.report_type,
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
        listing = "\n".join(f"{index}. {title}" for index, title in enumerate(candidates, start=1))
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

    async def classify_dm_intent(self, text: str) -> Literal["tasklist", "attendance"] | None:
        content = await self._chat_json(_DM_INTENT_SYSTEM_PROMPT, text)
        if content is None:
            return None
        try:
            draft = _DmIntentDraft.model_validate_json(content)
        except ValidationError:
            return None
        return draft.intent if draft.intent != "unknown" else None

    async def persona_reply(self, message: str) -> str | None:
        """Free-text conversational reply (greetings/intro/capability
        questions), grounded only in whatsapp.PERSONA_CAPABILITIES -- never
        business data. Separate call/prompt/timeout from interpret() so
        business-intent classification latency is unaffected (see
        _PERSONA_SYSTEM_PROMPT). None on any failure; caller falls back to
        whatsapp.PERSONA_FALLBACK_REPLY.
        """
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _PERSONA_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            "stream": False,
            "options": {"temperature": 0.3},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=_PERSONA_TIMEOUT_SECONDS
            ) as client:
                response = await client.post("/api/chat", json=payload)
                _ = response.raise_for_status()
                parsed = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError):
            return None
        content = parsed.message.content
        return content.strip() if content and content.strip() else None
