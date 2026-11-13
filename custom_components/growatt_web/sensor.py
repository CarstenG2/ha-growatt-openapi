"""Sensors for the Growatt Web integration.

Sensor names are the original Growatt field names. Units are assumptions
derived from the field names and from a plausibility check; Growatt does
not document them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GrowattWebConfigEntry
from .api import GrowattData
from .const import DOMAIN
from .coordinator import GrowattWebCoordinator

_LOGGER = logging.getLogger(__name__)


def to_float(value: Any) -> float | None:
    """Convert a portal value ("78", "0.24", 0.0) to float. None if empty."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        _LOGGER.error("Cannot convert Growatt value %r to a number", value)
        return None


def parse_portal_time(value: Any, tz_hours: Any) -> datetime | None:
    """Parse lastUpdateTime ("yyyy-MM-dd HH:mm:ss", plant local time).

    The offset comes from the device field ``timezone`` (e.g. 1.0). Whether
    that field follows daylight saving time is unverified.
    """
    if not value:
        return None
    try:
        naive = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        offset = timezone(timedelta(hours=float(tz_hours if tz_hours is not None else 0)))
    except (TypeError, ValueError):
        _LOGGER.error("Cannot parse Growatt time %r (timezone %r)", value, tz_hours)
        return None
    return naive.replace(tzinfo=offset)


@dataclass(frozen=True, kw_only=True)
class GrowattSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[GrowattData], Any]


def _status(field: str) -> Callable[[GrowattData], Any]:
    return lambda data: to_float(data.status.get(field))


def _day(field: str) -> Callable[[GrowattData], Any]:
    return lambda data: to_float(data.day_totals.get(field))


def _live(
    field: str,
    device_class: SensorDeviceClass | None,
    unit: str | None,
) -> GrowattSensorDescription:
    return GrowattSensorDescription(
        key=field.lower(),
        name=field,
        device_class=device_class,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT if unit else None,
        value_fn=_status(field),
    )


def _total(field: str) -> GrowattSensorDescription:
    return GrowattSensorDescription(
        key=field.lower(),
        name=field,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_day(field),
    )


V = UnitOfElectricPotential.VOLT
KW = UnitOfPower.KILO_WATT

SENSORS: tuple[GrowattSensorDescription, ...] = (
    _live("SOC", SensorDeviceClass.BATTERY, PERCENTAGE),
    _live("vBat", SensorDeviceClass.VOLTAGE, V),
    _live("chargePower", SensorDeviceClass.POWER, KW),
    _live("pdisCharge1", SensorDeviceClass.POWER, KW),
    _live("pactogrid", SensorDeviceClass.POWER, KW),
    _live("pactouser", SensorDeviceClass.POWER, KW),
    _live("pLocalLoad", SensorDeviceClass.POWER, KW),
    _live("ppv", SensorDeviceClass.POWER, KW),
    _live("vPv1", SensorDeviceClass.VOLTAGE, V),
    # Unit of pPv1/pPv2 is open (W or kW); left unitless until verified in daylight.
    _live("pPv1", None, None),
    _live("vPv2", SensorDeviceClass.VOLTAGE, V),
    _live("pPv2", None, None),
    _live("vAc1", SensorDeviceClass.VOLTAGE, V),
    _live("fAc", SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ),
    # Raw inverter status code as delivered (e.g. "5", "6"); text mapping unknown.
    GrowattSensorDescription(
        key="status",
        name="status",
        value_fn=lambda data: (
            None if data.status.get("status") in (None, "") else str(data.status["status"])
        ),
    ),
    _total("etouser"),
    _total("elocalLoad"),
    _total("eCharge"),
    _total("eAcCharge"),
    GrowattSensorDescription(
        key="lastupdatetime",
        name="lastUpdateTime",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: parse_portal_time(
            data.device_info.get("lastUpdateTime"), data.device_info.get("timezone")
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrowattWebConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create all sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [GrowattSensor(coordinator, d) for d in SENSORS]
    entities.append(LastSuccessfulPollSensor(coordinator))
    async_add_entities(entities)


def _device_info(coordinator: GrowattWebCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.device.serial)},
        name="Growatt Web",
        manufacturer="Growatt",
        model=coordinator.device.model,
        serial_number=coordinator.device.serial,
    )


class GrowattSensor(CoordinatorEntity[GrowattWebCoordinator], SensorEntity):
    """A value from the Growatt portal. Unavailable when the last poll failed."""

    _attr_has_entity_name = True
    entity_description: GrowattSensorDescription

    def __init__(
        self, coordinator: GrowattWebCoordinator, description: GrowattSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.serial}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class LastSuccessfulPollSensor(CoordinatorEntity[GrowattWebCoordinator], SensorEntity):
    """Time of the last successful poll. Keeps its value when a poll fails."""

    _attr_has_entity_name = True
    _attr_name = "Last successful poll"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: GrowattWebCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.serial}_last_successful_poll"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.last_success is not None

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_success

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
