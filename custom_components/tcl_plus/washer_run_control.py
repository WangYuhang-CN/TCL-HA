"""State guards for the washer's start and pause commands."""

from __future__ import annotations

from typing import Any

from .device import boolean_value, integer_value


def run_action_available(
    status: dict[str, Any],
    target: int,
    pending: bool,
    field: str = "lowerShellRunStatus",
) -> bool:
    """Allow only meaningful, known transitions while power is on."""
    if pending or boolean_value(status.get("powerSwitch")) is not True:
        return False
    current = integer_value(status.get(field))
    if target == 2:
        return current in (0, 1)
    if target == 1:
        return current == 2
    return False
