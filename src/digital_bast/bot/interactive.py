"""Transport-neutral button-first response contract.

Business handlers return this JSON envelope when useful. WhatsApp buttons don't
render reliably on this account, so wa-session's real fallback is a numbered
list -- a reply typed as a bare digit resolves back to the matching action id
before it reaches this service layer. The action ID is merely an input token;
authorization and state validation still happen in the Python workflow
services.

digit_shortcuts must be False when `text` already asks for a bare-number reply
for something else (e.g. picking an outstanding evidence/attendance item from
its own numbered list, as in dm_workflow._attendance_status_reply) -- without
it, wa-session's next-digit-selects-an-action shortcut would shadow that
existing, more specific numbered flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InteractiveAction:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class InteractiveReply:
    text: str
    actions: tuple[InteractiveAction, ...]
    footer: str = "Digital BAST"
    digit_shortcuts: bool = True

    def render(self) -> str:
        return json.dumps(
            {
                "kind": "interactive",
                "text": self.text,
                "footer": self.footer,
                "digitShortcuts": self.digit_shortcuts,
                "actions": [
                    {"id": action.id, "label": action.label} for action in self.actions
                ],
            },
            ensure_ascii=False,
        )


def interactive(
    text: str,
    *actions: tuple[str, str],
    footer: str = "Digital BAST",
    digit_shortcuts: bool = True,
) -> str:
    return InteractiveReply(
        text=text,
        actions=tuple(InteractiveAction(action_id, label) for action_id, label in actions),
        footer=footer,
        digit_shortcuts=digit_shortcuts,
    ).render()
