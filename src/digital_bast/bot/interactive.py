"""Transport-neutral button-first response contract.

Business handlers return this JSON envelope when useful. wa-session may render
native WhatsApp buttons when supported and must fall back to the same labels and
IDs as text. The action ID is merely an input token; authorization and state
validation still happen in the Python workflow services.
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

    def render(self) -> str:
        return json.dumps(
            {
                "kind": "interactive",
                "text": self.text,
                "footer": self.footer,
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
) -> str:
    return InteractiveReply(
        text=text,
        actions=tuple(InteractiveAction(action_id, label) for action_id, label in actions),
        footer=footer,
    ).render()
