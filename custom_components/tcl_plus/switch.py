"""Writable appliance booleans and array options."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TclRuntime
from .capabilities import control_key, entity_naming
from .control import TclPropertyControl
from .device import boolean_value

CONTROL_SWITCH_FIELDS = frozenset(
    {
        "powerSwitch",
        "nightWashMode",
        "speedUpMode",
        "soak",
        "freshWaterRinseMode",
        "ECO",
        "childLock",
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: TclRuntime = entry.runtime_data
    entities = []
    for device in runtime.devices:
        specs = runtime.coordinator.capabilities[device.device_id].control_specs
        for field, spec in specs.items():
            if spec["kind"] == "bool":
                entities.append(TclPropertySwitch(runtime.coordinator, device, field))
            elif spec["kind"] == "array":
                entities.extend(
                    TclPropertySwitch(runtime.coordinator, device, field, code)
                    for code, _ in spec["options"]
                )
    async_add_entities(entities)


class TclPropertySwitch(TclPropertyControl, SwitchEntity):
    """Write one model boolean or toggle one array option."""

    def __init__(self, coordinator, device, field: str, option: int | None = None):
        key = control_key(device, field, option)
        super().__init__(coordinator, device, field, key)
        self.option = option
        category = (
            EntityCategory.DIAGNOSTIC
            if field == "errorCode"
            else None
            if field in CONTROL_SWITCH_FIELDS or device.kind == "dryer"
            else EntityCategory.CONFIG
        )
        self.entity_description = SwitchEntityDescription(
            key=key,
            **entity_naming(
                device,
                coordinator.capabilities[device.device_id],
                field,
                control=True,
                option=option,
            ),
            entity_category=category,
            entity_registry_enabled_default=field != "errorCode",
        )

    @property
    def is_on(self) -> bool | None:
        value = self.status.get(self.field)
        if self.option is not None:
            if not isinstance(value, list):
                return None
            # The washer array lists disabled notifications; the dryer array lists faults.
            return (
                (self.option not in value)
                if self.device.kind == "washer"
                else (self.option in value)
            )
        return value if isinstance(value, bool) else boolean_value(value)

    async def async_turn_on(self, **kwargs) -> None:
        if self.option is not None:
            await self.async_set_array_option(self.option, self.device.kind == "dryer")
        else:
            await self.async_write_value(1)

    async def async_turn_off(self, **kwargs) -> None:
        if self.option is not None:
            await self.async_set_array_option(self.option, self.device.kind == "washer")
        else:
            await self.async_write_value(0)
