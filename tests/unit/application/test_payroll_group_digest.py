from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_closing_settings import PayrollClosingSettings
from digital_bast.application.payroll_digest import PayrollClosingDigest, PayrollDigestSummary
from digital_bast.application.payroll_group_digest import (
    PayrollGroupDigestDelivery,
    PayrollGroupDigestReservation,
    PayrollGroupDigestService,
)
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState
from digital_bast.application.talentops_followups import WhatsAppSendReceipt
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.whatsapp_directory import PayrollClosingGroupSetting

_CYCLE = payroll_cycle(2026, 9)
_H1 = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)
_FINAL = datetime(2026, 9, 20, 10, 0, tzinfo=JAKARTA)


class _Settings:
    def __init__(self, value: PayrollClosingSettings) -> None:
        self.value = value

    async def load(self, scope_key: str = "default") -> PayrollClosingSettings:
        assert scope_key == "default"
        return self.value

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        self.value = settings
        return settings

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        self.value = replace(self.value, applied_version=version)
        return self.value


class _Digest:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def project(self, cycle: object, **kwargs: object) -> PayrollClosingDigest:
        assert cycle == _CYCLE
        self.calls.append(str(kwargs["target_roles"]))
        return PayrollClosingDigest(
            cycle=_CYCLE,
            evaluated_through=_CYCLE.period.end,
            summary=PayrollDigestSummary(
                total_talents=10,
                complete=4,
                waiting_submitted=2,
                needs_talent_action=4,
                unverified=1,
                successful_reminder_deliveries=6,
                successfully_reminded_talents=5,
                unresponded_talents=2,
                actionable_not_reminded=1,
                delivery_retryable_failed=1,
                delivery_final_failed=0,
                delivery_unknown=1,
            ),
            items=(),
        )


class _Groups:
    def __init__(self, group_jid: str | None = "120363000-1@g.us") -> None:
        self.group_jid = group_jid

    async def closing_group(self, scope_key: str) -> PayrollClosingGroupSetting:
        return PayrollClosingGroupSetting(scope_key, self.group_jid)


class _Outbound:
    def __init__(self, receipt: WhatsAppSendReceipt | None = None) -> None:
        self.receipt = receipt or WhatsAppSendReceipt(
            status="sent",
            provider_message_id="wa-group-1",
        )
        self.calls: list[tuple[str, str, str]] = []

    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt:
        self.calls.append((group_jid, text, request_id))
        return self.receipt


class _Deliveries:
    def __init__(self) -> None:
        self.records: dict[str, PayrollGroupDigestDelivery] = {}

    async def reserve(  # noqa: PLR0913
        self,
        *,
        idempotency_key: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        group_jid: str,
        message: str,
        created_by: str,
    ) -> PayrollGroupDigestReservation:
        assert created_by == "payroll-scheduler"
        existing = self.records.get(idempotency_key)
        if existing is not None:
            return PayrollGroupDigestReservation(existing, False)
        record = PayrollGroupDigestDelivery(
            idempotency_key=idempotency_key,
            scope_key=scope_key,
            cycle_id=cycle_id,
            milestone=milestone,
            group_jid=group_jid,
            message=message,
            state=PayrollDeliveryState.RESERVED,
            attempt_count=0,
        )
        self.records[idempotency_key] = record
        return PayrollGroupDigestReservation(record, True)

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        group_jid: str,
        message: str,
    ) -> PayrollGroupDigestDelivery | None:
        record = self.records[idempotency_key]
        if record.state not in {PayrollDeliveryState.RESERVED, PayrollDeliveryState.FAILED_RETRYABLE}:
            return None
        updated = replace(
            record,
            group_jid=group_jid,
            message=message,
            state=PayrollDeliveryState.RESERVED,
            error_code=None,
        )
        self.records[idempotency_key] = updated
        return updated

    async def claim(self, idempotency_key: str) -> PayrollGroupDigestDelivery | None:
        record = self.records[idempotency_key]
        if record.state is not PayrollDeliveryState.RESERVED:
            return None
        updated = replace(
            record,
            state=PayrollDeliveryState.SENDING,
            attempt_count=record.attempt_count + 1,
        )
        self.records[idempotency_key] = updated
        return updated

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
    ) -> PayrollGroupDigestDelivery | None:
        record = self.records[idempotency_key]
        updated = replace(
            record,
            state=state,
            provider_message_id=provider_message_id,
            error_code=error_code,
        )
        self.records[idempotency_key] = updated
        return updated


def _service(
    *,
    enabled: bool = True,
    paused: bool = False,
    group_jid: str | None = "120363000-1@g.us",
    outbound: _Outbound | None = None,
    deliveries: _Deliveries | None = None,
) -> tuple[PayrollGroupDigestService, _Outbound, _Deliveries]:
    active_outbound = outbound or _Outbound()
    active_deliveries = deliveries or _Deliveries()
    service = PayrollGroupDigestService(
        "default",
        _Settings(PayrollClosingSettings(enabled=enabled, paused=paused)),
        _Digest(),
        _Groups(group_jid),
        active_outbound,
        active_deliveries,
    )
    return service, active_outbound, active_deliveries


async def test_h1_digest_sends_one_configured_group_message_and_deduplicates() -> None:
    service, outbound, deliveries = _service()

    first = await service.run(now=_H1)
    second = await service.run(now=_H1)

    assert first.outcome == "sent"
    assert first.milestone == "H-1"
    assert first.sent == 1
    assert second.outcome == "duplicate"
    assert len(outbound.calls) == 1
    assert len(deliveries.records) == 1
    group_jid, message, request_id = outbound.calls[0]
    assert group_jid == "120363000-1@g.us"
    assert "Perlu Talent: 4" in message
    assert "Belum merespons: 2" in message
    assert "UNKNOWN 1" in message
    assert request_id.endswith(":H-1")


async def test_final_digest_uses_final_milestone_on_cycle_end() -> None:
    service, outbound, _ = _service()

    result = await service.run(now=_FINAL)

    assert result.outcome == "sent"
    assert result.milestone == "FINAL"
    assert outbound.calls[0][2].endswith(":FINAL")


async def test_group_digest_respects_disabled_paused_and_missing_destination() -> None:
    disabled, disabled_outbound, _ = _service(enabled=False)
    paused, paused_outbound, _ = _service(paused=True)
    missing, missing_outbound, _ = _service(group_jid=None)

    assert (await disabled.run(now=_H1)).outcome == "disabled"
    assert (await paused.run(now=_H1)).outcome == "paused"
    assert (await missing.run(now=_H1)).outcome == "group_not_configured"
    assert disabled_outbound.calls == []
    assert paused_outbound.calls == []
    assert missing_outbound.calls == []


async def test_group_digest_retryable_failure_reuses_same_logical_delivery() -> None:
    outbound = _Outbound(
        WhatsAppSendReceipt(status="bridge_unavailable", error_code="bridge_down")
    )
    deliveries = _Deliveries()
    service, _, _ = _service(outbound=outbound, deliveries=deliveries)

    first = await service.run(now=_H1)
    outbound.receipt = WhatsAppSendReceipt(status="sent", provider_message_id="wa-2")
    second = await service.run(now=_H1)

    assert first.outcome == "failed_retryable"
    assert second.outcome == "sent"
    assert len(deliveries.records) == 1
    assert next(iter(deliveries.records.values())).attempt_count == 2
