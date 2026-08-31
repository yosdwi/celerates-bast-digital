"""LLM-backed interpreter for the WhatsApp bot (docs/bast-e2e-plan.md §3.5).

`create_llm_interpreter()` returning None -> this module is never called;
`parse_command()` alone drives the bot. When available, `LlmInterpreter.interpret()`
is the *primary* interpreter and `parse_command()` only runs as its fallback on any
failure -- timeout, non-JSON, schema violation, or an out-of-range period. That
ordering is deliberate: a regex match can silently be *wrong* (e.g. parsing the day
"20" out of the year "2026"), and only a fallback that runs after the LLM can catch
that class of error; a fallback that only triggers on regex UNKNOWN never sees it.

The model never computes a business value and never sees database contents --
only the user's message and today's date, or (for `choose_index`) a bounded
numbered list the caller already restricted to the sender's own candidates.

Talks to whatever TalentOpsChatClient operations.create_llm_interpreter() injects
(Cloudflare Workers AI in production) rather than calling Ollama directly -- the
same client abstraction application.talentops_ai already uses, so there's one
provider decision (LLM_PROVIDER), not two.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 -- pydantic needs this resolvable at runtime
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from digital_bast.bot.talent_context import (
    TalentConversationContext,
    TalentIntent,
    TalentInterpretation,
)
from digital_bast.bot.whatsapp import PERSONA_CAPABILITIES, PERSONA_NAME, BotCommand, Intent
from digital_bast.domain.completion import DateRange

if TYPE_CHECKING:
    from digital_bast.application.talentops_ai import TalentOpsChatClient

_MAX_SPAN_DAYS: Final = 366
_MAX_TALENT_PERIOD_DAYS: Final = 31
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


# Legacy DM classification is retained for cli.py's direct-evidence workflow.
# The new bound-Talent entrypoint uses _TALENT_DM_SYSTEM_PROMPT below instead:
# it carries period + conversational context and deliberately does not route
# on the mere presence of a keyword.
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

_TALENT_DM_SYSTEM_PROMPT: Final = (
    "Kamu adalah intent interpreter untuk chat pribadi seorang Talent di Digital BAST. "
    "Kamu HANYA menentukan tujuan navigasi dan periode; JANGAN menentukan readiness, "
    "approval, validitas evidence, atau nilai bisnis. Balas HANYA satu JSON valid:\n"
    '{"intent":"home|attendance|tasks|status|requests|group_only|conversation|unknown",'
    '"start_date":"YYYY-MM-DD atau null","end_date":"YYYY-MM-DD atau null"}\n'
    "Pahami MAKSUD SELURUH KALIMAT. Jangan memilih intent hanya karena satu keyword muncul. "
    "Kalimat yang hanya menyatakan fakta tanpa meminta data/aksi boleh unknown. Contoh: "
    '"tasklist kemarin sebenarnya sudah aku isi" -> unknown. '
    '"tasklist kemarin sudah aku isi, kok masih kurang?" -> tasks. '
    '"attendance bulan agustus 2026" -> attendance dengan 2026-08-01 s/d 2026-08-31. '
    '"yang masih kurang apa?" -> status. "pengajuan aku gimana?" -> requests.\n'
    "home untuk meminta menu/BAST Saya secara umum. attendance untuk attendance pribadi. "
    "tasks untuk Task & Evidence pribadi. status untuk menanyakan apa yang masih kurang/"
    "harus dikerjakan. requests untuk status pengajuan PMO. group_only untuk generate BAST, "
    "export attendance tim, atau status infrastruktur yang memang bukan capability Talent DM. "
    "conversation hanya untuk smalltalk/sapaan yang tidak meminta data. unknown jika ambigu.\n"
    "Jika user menyebut bulan/range, isi tanggal lengkap. Untuk satu nama bulan gunakan seluruh "
    "bulan tersebut; untuk bulan berjalan tanpa rentang eksplisit gunakan tanggal 1 sampai hari "
    "ini. Previous context boleh dipakai HANYA untuk follow-up yang jelas seperti 'yang pending "
    "mana?' atau saat user berganti domain tapi masih jelas membicarakan periode yang sama. "
    "Jika pesan menyebut periode baru, periode baru selalu menang."
)


class _DmIntentDraft(BaseModel):
    intent: Literal["tasklist", "attendance", "unknown"]


class _TalentDmDraft(BaseModel):
    intent: Literal[
        "home",
        "attendance",
        "tasks",
        "status",
        "requests",
        "group_only",
        "conversation",
        "unknown",
    ]
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _blank_string_is_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", ""}:
            return None
        return value


class _ChoiceDraft(BaseModel):
    choice: int | None = Field(default=None)


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


def _current_talent_period(today: date) -> DateRange:
    return DateRange(today.replace(day=1), today)


def _validate_talent_interpretation(
    draft: _TalentDmDraft,
    today: date,
    context: TalentConversationContext | None,
) -> TalentInterpretation | None:
    intent = TalentIntent(draft.intent)
    if intent in {TalentIntent.GROUP_ONLY, TalentIntent.CONVERSATION, TalentIntent.UNKNOWN}:
        return TalentInterpretation(intent)

    if draft.start_date is None and draft.end_date is None:
        period = context.period if context is not None else _current_talent_period(today)
        return TalentInterpretation(intent, period)
    if draft.start_date is None or draft.end_date is None:
        return None
    if draft.end_date < draft.start_date:
        return None
    if (
        draft.start_date.year != draft.end_date.year
        or draft.start_date.month != draft.end_date.month
        or (draft.end_date - draft.start_date).days + 1 > _MAX_TALENT_PERIOD_DAYS
    ):
        return None
    return TalentInterpretation(intent, DateRange(draft.start_date, draft.end_date))


class LlmInterpreter:
    def __init__(self, client: TalentOpsChatClient) -> None:
        self._client: TalentOpsChatClient = client

    async def interpret(self, text: str, today: date) -> BotCommand | None:
        content = await self._client.complete(
            _COMMAND_SYSTEM_PROMPT, f"Hari ini: {today.isoformat()}. Pesan: {text}"
        )
        if content is None:
            return None
        try:
            draft = BotCommandDraft.model_validate_json(content)
        except ValidationError:
            return None
        return _validate_command(draft)

    async def interpret_talent(
        self,
        text: str,
        today: date,
        context: TalentConversationContext | None = None,
    ) -> TalentInterpretation | None:
        context_text = "none"
        if context is not None:
            context_text = (
                f"{context.intent.value} {context.period.start.isoformat()}.."
                f"{context.period.end.isoformat()}"
            )
        user_prompt = (
            f"Hari ini: {today.isoformat()}\n"
            f"Previous context: {context_text}\n"
            f"Pesan: {text}"
        )
        content = await self._client.complete(_TALENT_DM_SYSTEM_PROMPT, user_prompt)
        if content is None:
            return None
        try:
            draft = _TalentDmDraft.model_validate_json(content)
        except ValidationError:
            return None
        return _validate_talent_interpretation(draft, today, context)

    async def choose_index(self, candidates: tuple[str, ...], message: str) -> int | None:
        listing = "\n".join(f"{index}. {title}" for index, title in enumerate(candidates, start=1))
        user_message = f"Daftar:\n{listing}\nPesan: {message}"
        content = await self._client.complete(_CHOICE_SYSTEM_PROMPT, user_message)
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
        content = await self._client.complete(_DM_INTENT_SYSTEM_PROMPT, text)
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
        business data. None on any failure; caller falls back to
        whatsapp.PERSONA_FALLBACK_REPLY.
        """
        return await self._client.complete(_PERSONA_SYSTEM_PROMPT, message)
