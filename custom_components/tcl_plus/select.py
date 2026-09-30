"""Enumerated controls generated from each product's own thing model."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
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
        TclPropertySelect(runtime.coordinator, device, field)
        for device in runtime.devices
        for field, spec in runtime.coordinator.capabilities[
            device.device_id
        ].control_specs.items()
        if spec["kind"] == "enum"
    )


class TclPropertySelect(TclPropertyControl, SelectEntity):
    """One enumerated property with its exact cloud codes."""

    def __init__(self, coordinator, device, field: str) -> None:
        key = control_key(device, field)
        super().__init__(coordinator, device, field, key)
        self.entity_description = SelectEntityDescription(
            key=key,
            **entity_naming(
                device, coordinator.capabilities[device.device_id], field, control=True
            ),
            entity_category=(
                None
                if field in ("lowerShellMode", "washShellMode")
                else EntityCategory.CONFIG
            ),
        )
        specs = coordinator.capabilities[device.device_id].control_specs
        labels = [label for _, label in specs[field]["options"]]
        self._code_to_option = {
            code: label
            if device.legacy_kind
            and field in ("lowerShellMode", "washShellMode")
            and labels.count(label) == 1
            else f"{code}: {label}"
            for code, label in specs[field]["options"]
        }
        self._option_to_code = {
            label: code for code, label in self._code_to_option.items()
        }

    @property
    def options(self) -> list[str]:
        spec = self.coordinator.capabilities[self.device.device_id].control_spec(
            self.field, self.reported_status
        )
        options = [self._code_to_option[code] for code, _ in spec["options"]]
        if self.device.legacy_kind and self.field in (
            "lowerShellMode",
            "washShellMode",
        ):
            ai_code = 35 if self.field == "lowerShellMode" else 27
            ai_option = self._code_to_option.get(ai_code)
            if ai_option in options:
                options.remove(ai_option)
                options.insert(0, ai_option)
        return options

    @property
    def available(self) -> bool:
        return super().available and bool(self.options)

    @property
    def current_option(self) -> str | None:
        code = integer_value(self.status.get(self.field))
        return self._code_to_option.get(code)

    async def async_select_option(self, option: str) -> None:
        code = self._option_to_code.get(option)
        if code is None:
            raise HomeAssistantError(f"Unsupported {self.field} option")
        await self.async_write_value(code)
