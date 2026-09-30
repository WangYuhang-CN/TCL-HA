"""Product-specific thing model parsing and conservative control discovery.

This module has no Home Assistant dependency. Unknown schemas keep their raw
status sensors, but never inherit another product's write constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import logging
import math
from typing import Any

from .api import TclApi, TclAuthError, TclError
from .device import TclDevice, integer_value
from .dryer_control_data import DRYER_CONTROL_SPECS
from .dryer_fields import DRYER_FIELDS
from .washer_control_data import WASHER_CONTROL_SPECS
from .washer_fields import WASHER_FIELDS, translation_key

_LOGGER = logging.getLogger(__name__)
MODE_CAPABILITIES = {
    "lowerShellMode": "lowerShellModeCapabilities",
    "washShellMode": "dryModeCapabilities",
}


@dataclass(frozen=True)
class ModelProperty:
    identifier: str
    name: str
    access_mode: str
    data_type: str
    spec: dict[str, Any] | None = None


@dataclass
class DeviceCapabilities:
    properties: dict[str, ModelProperty]
    control_specs: dict[str, dict[str, Any]]
    fields: set[str]
    source: str
    model_version: str = ""
    program_capabilities: dict[str, Any] = field(default_factory=dict)

    def observe_status(self, status: dict[str, Any]) -> None:
        """Retain the last reported program list even when a later status omits it."""
        self.fields.update(status)
        self.program_capabilities.update(
            {key: status[key] for key in MODE_CAPABILITIES.values() if key in status}
        )

    def name(self, field: str) -> str:
        prop = self.properties.get(field)
        return prop.name if prop else field

    def control_spec(self, field: str, status: dict[str, Any]) -> dict[str, Any]:
        """Intersect recognized program enums with this device's reported programs."""
        if field not in self.control_specs:
            raise ValueError(f"{field} is not a supported writable property")
        spec = self.control_specs[field]
        capability_field = MODE_CAPABILITIES.get(field)
        if spec["kind"] == "enum" and (
            capability_field in status or capability_field in self.program_capabilities
        ):
            codes = status.get(
                capability_field, self.program_capabilities.get(capability_field)
            )
            if not isinstance(codes, list) or any(
                integer_value(code) is None for code in codes
            ):
                return {**spec, "options": ()}
            allowed = {integer_value(code) for code in codes}
            return {
                **spec,
                "options": tuple(
                    (code, label) for code, label in spec["options"] if code in allowed
                ),
            }
        return spec


def _options(specs: Any) -> tuple[tuple[int, str], ...] | None:
    if not isinstance(specs, dict) or not specs:
        return None
    result = []
    seen = set()
    for raw_code, label in specs.items():
        code = integer_value(raw_code)
        if code is None or code in seen or not isinstance(label, str) or not label:
            return None
        seen.add(code)
        result.append((code, label))
    return tuple(result)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid numeric constraint")
    try:
        result = Decimal(str(value))
    except InvalidOperation as err:
        raise ValueError("Invalid numeric constraint") from err
    if not result.is_finite():
        raise ValueError("Non-finite numeric constraint")
    return result


def parse_spec(data_type: Any, *, allow_array: bool = False) -> dict[str, Any] | None:
    """Accept fully defined scalar schemas; array editing needs known semantics."""
    if not isinstance(data_type, dict):
        return None
    kind, specs = data_type.get("type"), data_type.get("specs")
    if not isinstance(specs, dict):
        return None
    if kind in ("bool", "enum"):
        options = _options(specs)
        if (
            options is None
            or kind == "bool"
            and {code for code, _ in options} != {0, 1}
        ):
            return None
        return {"kind": kind, "options": options}
    if kind in ("int", "int32", "int64", "float", "double"):
        # Do not guess a wire scaling factor from mappingType (e.g. int32_100).
        if data_type.get("mappingType", kind) not in (
            kind,
            "int" if kind.startswith("int") else kind,
        ):
            return None
        try:
            minimum, maximum, step = (
                _decimal(specs[key]) for key in ("min", "max", "step")
            )
            if minimum > maximum or step <= 0:
                return None
            integer = kind in ("int", "int32", "int64")
            if integer and any(
                value != value.to_integral_value() for value in (minimum, maximum, step)
            ):
                return None
            convert = int if integer else float
            values = [convert(value) for value in (minimum, maximum, step)]
            if not all(math.isfinite(value) for value in values) or values[2] <= 0:
                return None
            return {
                "kind": "int" if integer else "float",
                "minimum": values[0],
                "maximum": values[1],
                "step": values[2],
            }
        except (KeyError, ValueError, OverflowError):
            return None
    if kind == "array" and allow_array:
        item = specs.get("item")
        size = integer_value(specs.get("size"))
        options = (
            _options(item.get("specs"))
            if isinstance(item, dict) and item.get("type") == "enum"
            else None
        )
        if options is not None and size is not None and size > 0:
            return {"kind": "array", "options": options, "size": size}
    return None


def build_capabilities(
    device: TclDevice, model: dict[str, Any] | None
) -> DeviceCapabilities:
    """A live model is authoritative; archived fallbacks apply to exact products."""
    fields = set(device.initial_status)
    legacy = device.legacy_kind
    archived = (
        WASHER_CONTROL_SPECS
        if legacy == "washer"
        else DRYER_CONTROL_SPECS
        if legacy == "dryer"
        else {}
    )
    if legacy:
        fields.update(WASHER_FIELDS if legacy == "washer" else DRYER_FIELDS)
    programs = {
        key: device.initial_status[key]
        for key in MODE_CAPABILITIES.values()
        if key in device.initial_status
    }
    if model is None:
        controls = (
            {key: dict(spec) for key, spec in archived.items()}
            if device.controllable
            else {}
        )
        properties = {
            key: ModelProperty(key, key, "rw", spec["kind"], spec)
            for key, spec in archived.items()
        }
        return DeviceCapabilities(
            properties,
            controls,
            fields,
            "archived" if legacy else "status_only",
            program_capabilities=programs,
        )

    properties: dict[str, ModelProperty] = {}
    duplicates: set[str] = set()
    for prop in model.get("properties", []):
        if not isinstance(prop, dict):
            continue
        identifier = prop.get("identifier")
        if not isinstance(identifier, str) or not identifier:
            continue
        fields.add(identifier)
        if identifier in properties:
            duplicates.add(identifier)
        data_type = prop.get("dataType")
        kind = str(data_type.get("type", "")) if isinstance(data_type, dict) else ""
        properties[identifier] = ModelProperty(
            identifier,
            str(prop.get("name") or identifier),
            str(prop.get("accessMode", "")),
            kind,
            parse_spec(data_type, allow_array=True),
        )
    controls = {
        key: prop.spec
        for key, prop in properties.items()
        if device.controllable
        and prop.access_mode == "rw"
        and prop.spec is not None
        and key not in duplicates
        # Array writes need known semantics, even when their item enum is valid.
        and (prop.data_type != "array" or archived.get(key, {}).get("kind") == "array")
    }
    return DeviceCapabilities(
        properties,
        controls,
        fields,
        "cloud",
        str(model.get("tslVersion") or ""),
        programs,
    )


async def async_discover_capabilities(
    client: TclApi, devices: list[TclDevice]
) -> dict[str, DeviceCapabilities]:
    """Fetch each product once per setup, sharing its schema but not device state."""
    models: dict[str, dict[str, Any] | None] = {}
    result = {}
    for device in devices:
        if device.product_key not in models:
            try:
                models[device.product_key] = await client.async_get_model(
                    device.product_key
                )
            except TclAuthError:
                raise
            except TclError:
                models[device.product_key] = None
                _LOGGER.warning(
                    "Cannot load TCL+ product %s model; using available read-only state or an exact archived profile",
                    device.product_key,
                )
        result[device.device_id] = build_capabilities(
            device, models[device.product_key]
        )
    return result


def control_key(device: TclDevice, field: str, option: int | None = None) -> str:
    prefix = "dryer_" if device.legacy_kind == "dryer" else ""
    suffix = f"_{option}" if option is not None else ""
    return f"{prefix}control_{field}{suffix}"


def entity_naming(
    device: TclDevice,
    capabilities: DeviceCapabilities,
    field: str,
    *,
    control: bool = False,
    option: int | None = None,
) -> dict[str, str]:
    """Keep existing translations; give new fields names from their own model."""
    legacy = device.legacy_kind
    archived = WASHER_CONTROL_SPECS if legacy == "washer" else DRYER_CONTROL_SPECS
    fields = WASHER_FIELDS if legacy == "washer" else DRYER_FIELDS
    known = field in archived if control else field in fields
    if control and known:
        current = capabilities.control_specs.get(field, {})
        known = current.get("kind") == archived[field]["kind"]
    if (
        legacy
        and known
        and (
            option is None or option in {code for code, _ in archived[field]["options"]}
        )
    ):
        prefix = "dryer_" if legacy == "dryer" else ""
        key = translation_key(field)
        if control:
            key = key.replace("raw_", "control_", 1)
        return {
            "translation_key": prefix
            + key
            + (f"_{option}" if option is not None else "")
        }
    name = capabilities.name(field)
    if option is not None:
        label = dict(capabilities.control_specs[field]["options"]).get(
            option, str(option)
        )
        name = f"{name}: {label}"
    return {"name": name}


def validate_spec_value(
    field: str, value: Any, spec: dict[str, Any]
) -> int | float | list[int]:
    """Validate immediately before sending, including per-device program limits."""
    kind = spec["kind"]
    if kind == "array":
        allowed = {code for code, _ in spec["options"]}
        if (
            not isinstance(value, list)
            or len(value) > spec["size"]
            or any(type(item) is not int or item not in allowed for item in value)
            or len(value) != len(set(value))
        ):
            raise ValueError(f"Invalid {field} array value")
        return value
    if kind in ("bool", "enum"):
        if type(value) is not int or value not in {code for code, _ in spec["options"]}:
            raise ValueError(f"Invalid {field} option")
        return value
    if (
        kind == "int"
        and type(value) is not int
        or kind == "float"
        and type(value) not in (int, float)
    ):
        raise ValueError(f"Invalid {field} numeric value")
    if kind not in ("int", "float"):
        raise ValueError(f"Unsupported {field} type")
    number, minimum, maximum, step = (
        _decimal(item)
        for item in (value, spec["minimum"], spec["maximum"], spec["step"])
    )
    if (
        not minimum <= number <= maximum
        or (Fraction(number) - Fraction(minimum)) % Fraction(step) != 0
    ):
        raise ValueError(f"{field} is outside the supported range or step")
    return float(value) if kind == "float" else value
