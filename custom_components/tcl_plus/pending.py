"""Track accepted writes until the cloud status actually confirms them."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any, Callable

from .device import integer_value


@dataclass(frozen=True)
class PendingWrite:
    """An ACKed control request awaiting a matching status response."""

    value: int | float | list[int]
    deadline: float
    generation: int


def values_match(actual: Any, expected: int | float | list[int]) -> bool:
    """Match cloud strings/integers and order-independent enum arrays."""
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        actual_values = [integer_value(item) for item in actual]
        return None not in actual_values and sorted(actual_values) == sorted(expected)
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, (int, float, str)):
            return False
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except InvalidOperation:
            return False
    if isinstance(actual, bool):
        return expected in (0, 1) and int(actual) == expected
    return integer_value(actual) == expected


class PendingWrites:
    """Pure pending-write state shared by all entities on one coordinator."""

    def __init__(self, timeout: float, clock: Callable[[], float] = monotonic):
        self.timeout = timeout
        self.clock = clock
        self._generation = 0
        self._writes: dict[tuple[str, str], PendingWrite] = {}

    def register(
        self, device_id: str, field: str, value: int | float | list[int]
    ) -> int:
        self._generation += 1
        self._writes[(device_id, field)] = PendingWrite(
            value.copy() if isinstance(value, list) else value,
            self.clock() + self.timeout,
            self._generation,
        )
        return self._generation

    def get(self, device_id: str, field: str) -> PendingWrite | None:
        return self._writes.get((device_id, field))

    def is_current(self, device_id: str, field: str, generation: int) -> bool:
        write = self.get(device_id, field)
        return write is not None and write.generation == generation

    def effective_status(
        self, device_id: str, reported: dict[str, Any]
    ) -> dict[str, Any]:
        """Overlay desired values while their cloud confirmation is pending."""
        effective = reported.copy()
        for (pending_device, field), write in self._writes.items():
            if pending_device == device_id:
                effective[field] = write.value
        return effective

    def observe(self, device_id: str, reported: dict[str, Any]) -> list[str]:
        """Clear writes the cloud has confirmed; return their field names."""
        confirmed: list[str] = []
        for (pending_device, field), write in tuple(self._writes.items()):
            if pending_device == device_id and values_match(
                reported.get(field), write.value
            ):
                del self._writes[(device_id, field)]
                confirmed.append(field)
        return confirmed

    def expire(self, device_id: str, field: str, generation: int) -> bool:
        """Remove only the same write after its deadline; newer writes survive."""
        write = self.get(device_id, field)
        if (
            write is None
            or write.generation != generation
            or self.clock() < write.deadline
        ):
            return False
        del self._writes[(device_id, field)]
        return True
