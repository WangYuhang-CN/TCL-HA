"""Numeric controls with product-specific limits and steps."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TclRuntime
from .capabilities import control_key, entity_naming
from .control import TclPropertyControl
from .device import integer_value


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: TclRuntime = entry.runtime_data
    async_add_entities(
        TclPropertyNumber(runtime.coordinator, device, field)
        for device in runtime.devices
        for field, spec in runtime.coordinator.capabilities[
            device.device_id
        ].control_specs.items()
        if spec["kind"] in ("int", "float")
    )


class TclPropertyNumber(TclPropertyControl, NumberEntity):
    """One numeric field constrained by its own product's thing model."""

    def __init__(self, coordinator, device, field: str) -> None:
        key = control_key(device, field)
        super().__init__(coordinator, device, field, key)
        self.entity_description = NumberEntityDescription(
            key=key,
            **entity_naming(
                device, coordinator.capabilities[device.device_id], field, control=True
            ),
            entity_category=EntityCategory.CONFIG,
        )
        spec = coordinator.capabilities[device.device_id].control_specs[field]
        self.integer = spec["kind"] == "int"
        self._attr_native_min_value = spec["minimum"]
        self._attr_native_max_value = spec["maximum"]
        self._attr_native_step = spec["step"]

    @property
    def native_value(self) -> float | None:
        value = self.status.get(self.field)
        if self.integer:
            return integer_value(value)
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (ValueError, TypeError, OverflowError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise HomeAssistantError(f"{self.field} only accepts finite numbers")
        if self.integer and not float(value).is_integer():
            raise HomeAssistantError(f"{self.field} only accepts whole numbers")
        await self.async_write_value(int(value) if self.integer else value)
