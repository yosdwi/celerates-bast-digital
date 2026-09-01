"""Canonical Talent onboarding phrase from the PMO usage guideline.

The documented first message is ``Halo, saya <NRP>``. When that exact shape
contains an exact roster NRP, the bot may bind immediately and open the Talent
home. We intentionally do not use typo/fuzzy matching on this direct-bind path.
If the employee is already bound to another WhatsApp number, the existing PMO
rebind workflow remains mandatory and no identity is taken over automatically.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Final

from digital_bast.bot.identity import ActivationOutcome
from digital_bast.bot.interactive import interactive
from digital_bast.bot.talent_home import home as talent_home
from digital_bast.domain.completion import DateRange
from digital_bast.domain.identity import canonical_text
from digital_bast.domain.time import JAKARTA
from digital_bast.operations import (
    create_activation_service,
    create_identity_rebind_service,
    create_rebind_onboarding_service,
    load_roster,
)

_GUIDELINE_NRP: Final = re.compile(
    r"^\s*(?:halo|hai|hi)\s*[,!.-]*\s*(?:saya|aku)\s+([a-z0-9_-]+)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_CLOSEOUT_GRACE_DAYS: Final = 7
_MASK_THRESHOLD: Final = 6


def guideline_nrp(text: str) -> str | None:
    match = _GUIDELINE_NRP.fullmatch(text)
    return match.group(1).strip() if match is not None else None


def _default_period() -> DateRange:
    today = datetime.now(JAKARTA).date()
    if today.day <= _CLOSEOUT_GRACE_DAYS:
        last_previous = today.replace(day=1) - timedelta(days=1)
        return DateRange(last_previous.replace(day=1), last_previous)
    return DateRange(today.replace(day=1), today)


def _mask_jid(jid: str) -> str:
    number = jid.split("@", 1)[0]
    if len(number) <= _MASK_THRESHOLD:
        return number
    return f"{number[:3]}***{number[-3:]}"


def _rebind_prompt(existing_jid: str) -> str:
    body = (
        "NRP ini sudah terhubung ke WhatsApp lain.\n"
        f"Binding aktif: {_mask_jid(existing_jid)}\n\n"
        "Kalau ini nomor barumu, ajukan ganti nomor. "
        "Nomor lama tetap aktif sampai PMO approve."
    )
    return interactive(
        body,
        ("rebind:submit", "Ajukan Ganti Nomor"),
        ("rebind:cancel", "Batal"),
    )


async def try_guideline_onboarding(  # noqa: PLR0911 - explicit identity guards
    text: str,
    jid: str,
) -> str | None:
    nrp = guideline_nrp(text)
    if nrp is None:
        return None

    roster = await load_roster()
    needle = canonical_text(nrp)
    matches = tuple(
        employee
        for employee in roster
        if canonical_text(employee.external_id) == needle
    )
    if len(matches) != 1:
        return (
            f'NRP "{nrp}" belum aku kenali. Pastikan formatnya benar, contoh: '
            '"Halo, saya JIMT24001".'
        )
    employee = matches[0]
    employee_id = str(employee.id)

    activation = create_activation_service()
    current = await activation.resolve(jid)
    if current is not None:
        if current == employee_id:
            return await talent_home(employee_id, period=_default_period())
        return "Nomor WhatsApp ini sudah terhubung ke Talent lain. Hubungi PMO/Admin."

    existing_jid = await create_rebind_onboarding_service().existing_jid(employee_id)
    if existing_jid is not None and existing_jid != jid:
        await create_identity_rebind_service().stage(jid, employee_id)
        return _rebind_prompt(existing_jid)

    outcome = await activation.bind(jid, employee_id)
    if outcome is ActivationOutcome.SUCCESS:
        return await talent_home(employee_id, period=_default_period())

    # Fail closed on a race: never overwrite a binding created concurrently.
    existing_jid = await create_rebind_onboarding_service().existing_jid(employee_id)
    if existing_jid is not None and existing_jid != jid:
        await create_identity_rebind_service().stage(jid, employee_id)
        return _rebind_prompt(existing_jid)
    return "Onboarding belum bisa diselesaikan. Coba kirim ulang NRP atau hubungi PMO."
