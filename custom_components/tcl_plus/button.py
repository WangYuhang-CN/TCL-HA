"""Direct appliance actions for the device page and simple dashboard."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TclRuntime
from .control import TclPropertyControl
from .device import running_field
from .washer_run_control import run_action_available


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: TclRuntime = entry.runtime_data
    entities = []
    for device in runtime.devices:
        if not device.legacy_kind:
            continue
        specs = runtime.coordinator.capabilities[device.device_id].control_specs
        if specs.get("powerSwitch", {}).get("kind") == "bool":
            entities.append(TclPowerOn(runtime.coordinator, device))
            run_spec = specs.get(running_field(device), {})
            if run_spec.get("kind") == "enum" and {0, 1, 2}.issubset(
                code for code, _ in run_spec["options"]
            ):
                entities.extend(
                    (
                        TclRunButton(runtime.coordinator, device, "start", 2),
                        TclRunButton(runtime.coordinator, device, "pause", 1),
                    )
                )
    async_add_entities(entities)


class TclPowerOn(TclPropertyControl, ButtonEntity):
    """Turn on a supported appliance."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device, "powerSwitch", "power_on")
        self._attr_translation_key = f"{device.kind}_power_on"

    async def async_press(self) -> None:
        await self.async_write_value(1)


class TclRunButton(TclPropertyControl, ButtonEntity):
    """Start, resume or pause via the documented run-state property."""

    def __init__(self, coordinator, device, action: str, target: int) -> None:
        super().__init__(coordinator, device, running_field(device), f"run_{action}")
        self.target = target
        self._attr_translation_key = f"{device.kind}_{action}"
        self._attr_icon = "mdi:play" if target == 2 else "mdi:pause"

    @property
    def available(self) -> bool:
        pending_fields = (self.field,)
        if self.target == 2:
            mode_field = (
                "lowerShellMode" if self.device.kind == "washer" else "washShellMode"
            )
            pending_fields += ("powerSwitch", mode_field)
        return super().available and run_action_available(
            self.status,
            self.target,
            any(
                self.coordinator.last_write_status.get((self.device.device_id, field))
                == "pending"
                for field in pending_fields
            ),
            self.field,
        )

    async def async_press(self) -> None:
        async with self.coordinator.write_locks[self.device.device_id]:
            if not self.available:
                raise HomeAssistantError(
                    f"{self.device.kind} action is unavailable in its current state"
                )
            await self._async_write_value_unlocked(self.target)
