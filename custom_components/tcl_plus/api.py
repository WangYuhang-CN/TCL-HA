"""Async client for the observed domestic TCL+ cloud endpoints."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
import json
import secrets
import time
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    APP_ID,
    APP_SECRET,
    AUTH_BASE_URL,
    IOT_BASE_URL,
    STORE_UUID,
    TENANT_ID,
)


class TclError(Exception):
    """Base error for TCL+ requests."""


class TclConnectionError(TclError):
    """Transport or server failure."""


class TclAuthError(TclError):
    """Stored credentials could not be used or refreshed."""


class TclQrPending(TclError):
    """QR authorization has not completed."""


class TclQrExpired(TclError):
    """The QR authorization is no longer valid."""


@dataclass(frozen=True)
class TclQrCode:
    code: str
    image_url: str


class TclApi:
    """The observed domestic TCL+ API for model-driven appliance integration."""

    def __init__(
        self,
        session: ClientSession,
        access_token: str = "",
        refresh_token: str = "",
        on_tokens: Callable[[str, str], None] | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._on_tokens = on_tokens
        self._refresh_lock = asyncio.Lock()

    async def async_create_qr(self) -> TclQrCode:
        payload = await self._request(
            "GET",
            AUTH_BASE_URL + "/auth/common/v2/getQRCodePic",
            params={
                "appId": APP_ID,
                "width": "400",
                "height": "400",
                "to": "qrlogin",
                "deviceName": "tcl-plus-ha",
                "from": f"tcl-plus-ha_{int(time.time() * 1000)}",
            },
        )
        data = payload.get("data")
        if payload.get("status") != 1 or not isinstance(data, dict):
            raise TclConnectionError("Could not create TCL+ QR code")
        code, image_url = data.get("code"), data.get("imageUrl")
        if not isinstance(code, str) or not code:
            raise TclConnectionError("TCL+ QR response has no code")
        if not isinstance(image_url, str) or not image_url.startswith(
            AUTH_BASE_URL + "/"
        ):
            raise TclConnectionError("TCL+ QR response has no trusted image URL")
        return TclQrCode(code, image_url)

    async def async_check_qr(self, code: str) -> tuple[str, str]:
        payload = await self._request(
            "GET",
            AUTH_BASE_URL + "/auth/common/v2/checkQRCodeAuthor",
            params={"code": code},
        )
        data = payload.get("data")
        if payload.get("status") == 1 and isinstance(data, dict):
            token, refresh_token = data.get("token"), data.get("refreshToken")
            if (
                isinstance(token, str)
                and token
                and isinstance(refresh_token, str)
                and refresh_token
            ):
                self._access_token, self._refresh_token = token, refresh_token
                return token, refresh_token
        message = str(payload.get("msg", "")).lower()
        if "expir" in message or "过期" in message or "失效" in message:
            raise TclQrExpired("TCL+ QR code expired")
        raise TclQrPending("TCL+ QR authorization is pending")

    async def async_list_devices(self) -> list[dict[str, Any]]:
        payload = await self._iot_request(
            "GET", "/v1/tclplus/user/user_devices/openclaw"
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise TclConnectionError("TCL+ device list has an unexpected shape")
        return data

    async def async_get_status(self, device_id: str) -> dict[str, Any]:
        payload = await self._iot_request(
            "POST", "/v1/thing/status/openclaw", json={"deviceId": device_id}
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("status"), dict):
            raise TclConnectionError("TCL+ status has an unexpected shape")
        return data["status"]

    async def async_get_model(self, product_key: str) -> dict[str, Any]:
        """Get the product's own property definitions, rather than a family template."""
        payload = await self._iot_request(
            "GET", f"/tsl/{quote(product_key, safe='')}/tsl/openclaw"
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("properties"), list):
            raise TclConnectionError("TCL+ thing model has an unexpected shape")
        if str(data.get("productKey", "")) != product_key:
            raise TclConnectionError("TCL+ thing model belongs to another product")
        return data

    async def async_set_property(
        self, device_id: str, key: str, value: int | float | list[int]
    ) -> None:
        await self._iot_request(
            "POST",
            f"/v1/control/property/{quote(device_id, safe='')}/openclaw",
            json={
                "msgId": secrets.token_hex(16),
                "params": [{key: value}],
                "version": "1.0",
            },
        )

    async def _iot_request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        if not self._access_token:
            raise TclAuthError("No TCL+ access token")
        if self._token_expiring_soon(self._access_token):
            await self._refresh(self._access_token)
        old_token = self._access_token
        try:
            return await self._send_iot(method, path, **kwargs)
        except TclAuthError:
            await self._refresh(old_token)
            return await self._send_iot(method, path, **kwargs)

    async def _send_iot(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        payload = await self._request(
            method,
            IOT_BASE_URL + path,
            headers={
                "accessToken": self._access_token,
                "Content-Type": "application/json",
                "t-store-uuid": STORE_UUID,
            },
            **kwargs,
        )
        code = str(payload.get("code", ""))
        message = str(payload.get("message") or payload.get("msg") or "").lower()
        if code == "401" or (
            "token" in message
            and any(
                term in message
                for term in ("expired", "invalid", "expire", "过期", "失效", "无效")
            )
        ):
            raise TclAuthError("TCL+ access token rejected")
        if payload.get("success") is False or (
            code not in ("200", "1") and payload.get("success") is not True
        ):
            raise TclError(f"TCL+ API returned code {code or 'missing'}")
        return payload

    async def _refresh(self, previous_token: str) -> None:
        async with self._refresh_lock:
            if self._access_token != previous_token:
                return
            if not self._refresh_token:
                raise TclAuthError("No TCL+ refresh token")
            try:
                payload = await self._request(
                    "POST",
                    AUTH_BASE_URL + "/auth/auth/refershToken",
                    params={
                        "appId": APP_ID,
                        "appSecret": APP_SECRET,
                        "tenantId": TENANT_ID,
                    },
                    headers={"refreshToken": self._refresh_token},
                )
            except TclConnectionError:
                raise
            except TclError as err:
                raise TclAuthError("TCL+ token refresh failed") from err
            if str(payload.get("code")) != "1":
                raise TclAuthError("TCL+ token refresh rejected")
            token, refresh_token = (
                payload.get("accessToken"),
                payload.get("refreshToken"),
            )
            if (
                not isinstance(token, str)
                or not token
                or not isinstance(refresh_token, str)
                or not refresh_token
            ):
                raise TclAuthError("TCL+ token refresh response is incomplete")
            self._access_token, self._refresh_token = token, refresh_token
            if self._on_tokens is not None:
                self._on_tokens(token, refresh_token)

    @staticmethod
    def _token_expiring_soon(token: str) -> bool:
        try:
            encoded = token.split(".")[1]
            payload = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            )
            expiry = payload.get("exp")
            return isinstance(expiry, (int, float)) and expiry <= time.time() + 300
        except (AttributeError, binascii.Error, IndexError, ValueError, TypeError):
            return False

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(
                method, url, timeout=ClientTimeout(total=30), **kwargs
            ) as response:
                if response.status == 401:
                    raise TclAuthError("TCL+ returned HTTP 401")
                if response.status >= 400:
                    raise TclConnectionError(f"TCL+ returned HTTP {response.status}")
                payload = await response.json(content_type=None)
        except (ClientError, asyncio.TimeoutError, ValueError) as err:
            raise TclConnectionError("TCL+ request failed") from err
        if not isinstance(payload, dict):
            raise TclConnectionError("TCL+ response is not a JSON object")
        return payload
