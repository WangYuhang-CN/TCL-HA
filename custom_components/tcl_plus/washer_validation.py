"""Pure validation for washer property writes."""

from __future__ import annotations

from typing import Any

from .washer_control_data import WASHER_CONTROL_SPECS
from .dryer_control_data import DRYER_CONTROL_SPECS
from .capabilities import validate_spec_value


def validate_control_value(
    field: str, value: Any, kind: str = "washer"
) -> int | list[int]:
    """Accept only values within the captured model's declared constraints."""
    spec = (WASHER_CONTROL_SPECS if kind == "washer" else DRYER_CONTROL_SPECS)[field]
    return validate_spec_value(field, value, spec)
