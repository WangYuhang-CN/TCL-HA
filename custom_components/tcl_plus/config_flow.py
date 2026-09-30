"""QR based setup and reauthorization for TCL+."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import TclApi, TclError, TclQrCode, TclQrExpired, TclQrPending
from .const import CONF_ACCESS_TOKEN, CONF_DEVICE_IDS, CONF_REFRESH_TOKEN, DOMAIN
from .device import supported_devices


class TclPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Authorize the account by scanning a TCL+ QR code."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: TclApi | None = None
        self._qr: TclQrCode | None = None
        self._credentials: tuple[str, str] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a QR code when setup begins."""
        self._client = TclApi(async_get_clientsession(self.hass))
        self._credentials = None
        try:
            self._qr = await self._client.async_create_qr()
        except TclError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )
        return await self.async_step_scan()

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Check authorization after the user confirms it in the TCL+ app."""
        if self._client is None or self._qr is None:
            return await self.async_step_user()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("new_code"):
                return await self.async_step_user()
            try:
                if self._credentials is None:
                    self._credentials = await self._client.async_check_qr(self._qr.code)
                token, refresh_token = self._credentials
                devices = supported_devices(await self._client.async_list_devices())
            except TclQrExpired:
                errors["base"] = "qr_expired"
            except TclQrPending:
                errors["base"] = "qr_pending"
            except TclError:
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                elif self.source == SOURCE_REAUTH and not set(
                    self._get_reauth_entry().data.get(CONF_DEVICE_IDS, [])
                ).intersection(device.device_id for device in devices):
                    errors["base"] = "wrong_account"
                else:
                    data = {
                        CONF_ACCESS_TOKEN: token,
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_DEVICE_IDS: [device.device_id for device in devices],
                    }
                    if self.source == SOURCE_REAUTH:
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(), data_updates=data
                        )
                    return self.async_create_entry(title="TCL+", data=data)

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema({vol.Optional("new_code", default=False): bool}),
            description_placeholders={"qr_url": self._qr.image_url},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start a fresh QR authorization after a credential failure."""
        return await self.async_step_user()
