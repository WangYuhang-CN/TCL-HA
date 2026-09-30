"""Common TCL+ entity properties."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TclCoordinator
from .device import TclDevice


class TclEntity(CoordinatorEntity[TclCoordinator]):
    """An entity belonging to one TCL+ appliance."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TclCoordinator, device: TclDevice, key: str
    ) -> None:
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            manufacturer="TCL",
            name=device.name,
            model=device.model,
        )

    @property
    def status(self) -> dict[str, Any]:
        """Cloud status with ACKed writes held until the cloud confirms them."""
        return self.coordinator.effective_status(self.device.device_id)

    @property
    def reported_status(self) -> dict[str, Any]:
        """Unmodified latest cloud status for diagnostics."""
        return self.coordinator.data.get(self.device.device_id, {})

    @property
    def available(self) -> bool:
        """A failed request only makes its own appliance unavailable."""
        return super().available and self.device.device_id in self.coordinator.data
