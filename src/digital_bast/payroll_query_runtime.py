"""Runtime assembly for grounded Payroll closing queries."""

from __future__ import annotations

from digital_bast.application.payroll_query import (
    PayrollClosingQueryAi,
    PayrollClosingQueryService,
)
from digital_bast.config import get_settings
from digital_bast.infrastructure.cloudflare_workers_ai_chat import CloudflareWorkersAiChatClient
from digital_bast.payroll_runtime import create_payroll_digest_service


def create_payroll_closing_query_service(
    scope_key: str = "default",
) -> PayrollClosingQueryService:
    settings = get_settings()
    ai: PayrollClosingQueryAi | None = None
    if settings.cloudflare_account_id is not None and settings.cloudflare_api_token is not None:
        ai = PayrollClosingQueryAi(
            CloudflareWorkersAiChatClient(
                settings.cloudflare_account_id,
                settings.cloudflare_api_token.get_secret_value(),
                settings.cloudflare_workers_ai_model,
            )
        )
    return PayrollClosingQueryService(create_payroll_digest_service(scope_key), ai)
