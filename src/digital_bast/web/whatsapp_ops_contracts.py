from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic runtime metadata
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        from_attributes=True,
    )


class WhatsAppOperationsStatusResponse(_FrozenModel):
    alive: bool
    ready: bool
    connection: str
    me: str
    qr_data_url: str | None
    pairing_code: str | None
    operator_action_required: bool
    operator_reason: str | None
    connection_changed_at: datetime | None
    recovery_state: str
    recovery_reason: str | None
    recovery_paused: bool
    last_probe_at: datetime | None
    last_ready_at: datetime | None
    last_ack_at: datetime | None
    cooldown_until: datetime | None
    recovery_attempts: int
    recovery_max_attempts: int
    recovery_policy_version: int
    applied_recovery_policy_version: int
    owner_acquired: bool
    owner_conflict_id: str | None
    owner_conflict_heartbeat_at: datetime | None
    storage_healthy: bool
    storage_reasons: tuple[str, ...]
    free_bytes: int | None
    free_inodes: int | None
    receipt_store_healthy: bool
    receipt_store_error: str | None
    receipt_sent: int
    receipt_unknown: int
    receipt_in_flight: int
    transport: str


class WhatsAppOperationsControlResponse(_FrozenModel):
    accepted: bool
    reason: str
