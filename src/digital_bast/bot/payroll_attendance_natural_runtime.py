"""Runtime factory for the typed Payroll attendance natural interpreter."""

from __future__ import annotations

from digital_bast.bot.payroll_attendance_natural import PayrollAttendanceNaturalInterpreter
from digital_bast.config import get_settings
from digital_bast.infrastructure.cloudflare_workers_ai_chat import CloudflareWorkersAiChatClient


def create_payroll_attendance_natural_interpreter() -> PayrollAttendanceNaturalInterpreter | None:
    settings = get_settings()
    if settings.cloudflare_account_id is None or settings.cloudflare_api_token is None:
        return None
    return PayrollAttendanceNaturalInterpreter(
        CloudflareWorkersAiChatClient(
            settings.cloudflare_account_id,
            settings.cloudflare_api_token.get_secret_value(),
            settings.cloudflare_workers_ai_model,
        )
    )
