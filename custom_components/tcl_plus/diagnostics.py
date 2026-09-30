"""Schema diagnostics without account credentials or reported network values."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import TclRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    runtime: TclRuntime = entry.runtime_data
    return {
        "devices": [
            {
                "model": device.model,
                "product_key": device.product_key,
                "category": device.category,
                "controllable": device.controllable,
                "model_source": runtime.coordinator.capabilities[
                    device.device_id
                ].source,
                "model_version": runtime.coordinator.capabilities[
                    device.device_id
                ].model_version,
                "fields": sorted(
                    runtime.coordinator.capabilities[device.device_id].fields
                ),
                "controls": runtime.coordinator.capabilities[
                    device.device_id
                ].control_specs,
            }
            for device in runtime.devices
        ]
    }
