"""Device and state parsing, independent of Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DRYER_PRODUCT_KEY, WASHER_PRODUCT_KEY


@dataclass(frozen=True)
class TclDevice:
    """A cloud appliance; category selects a family, not a model allowlist."""

    device_id: str
    product_key: str
    name: str
    model: str
    kind: str
    category: str = ""
    initial_status: dict[str, Any] = field(default_factory=dict, compare=False)
    controllable: bool = True

    @property
    def legacy_kind(self) -> str | None:
        """Only use inspected action semantics and translations on these products."""
        if self.product_key == WASHER_PRODUCT_KEY and self.kind == "washer":
            return "washer"
        if self.product_key == DRYER_PRODUCT_KEY and self.kind == "dryer":
            return "dryer"
        return None


def supported_devices(items: list[dict[str, Any]]) -> list[TclDevice]:
    """Discover all identifiable domestic TCL+ appliances without model filtering."""
    result: list[TclDevice] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        product_key = item.get("productKey")
        if isinstance(product_key, bool) or not isinstance(product_key, (str, int)):
            continue
        product_key = str(product_key).strip()
        if not product_key:
            continue
        category = str(item.get("category") or "").upper()
        kind = {"DW": "washer", "DRY": "dryer"}.get(category, "generic")
        model = str(item.get("deviceType") or product_key)
        if product_key == DRYER_PRODUCT_KEY and kind == "dryer":
            model = "H100T7R-BS"
        device_id = item.get("deviceId")
        if not isinstance(device_id, str) or not device_id or device_id in seen:
            continue
        seen.add(device_id)
        name = item.get("nickName") or item.get("deviceName") or model
        identifiers = item.get("identifiers")
        initial_status = (
            {
                prop["identifier"]: prop.get("value")
                for prop in identifiers
                if isinstance(prop, dict)
                and isinstance(prop.get("identifier"), str)
                and prop["identifier"]
            }
            if isinstance(identifiers, list)
            else {}
        )
        result.append(
            TclDevice(
                device_id,
                product_key,
                str(name),
                model,
                kind,
                category,
                initial_status,
                item.get("isControl") is not False
                and integer_value(item.get("isControl")) != 0,
            )
        )
    return result


def integer_value(value: Any) -> int | None:
    """Parse cloud enum values without treating a nonempty '0' as true."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def boolean_value(value: Any) -> bool | None:
    """Return a boolean only for the documented 0/1 values."""
    number = integer_value(value)
    if number in (0, 1):
        return bool(number)
    return None


def running_field(device: TclDevice) -> str:
    return "lowerShellRunStatus" if device.kind == "washer" else "washShellRunStatus"


def active_status(device: TclDevice, status: dict[str, Any]) -> bool:
    """Whether a remaining-time value describes an active or paused cycle."""
    return boolean_value(status.get("powerSwitch")) is True and integer_value(
        status.get(running_field(device))
    ) in (1, 2)
