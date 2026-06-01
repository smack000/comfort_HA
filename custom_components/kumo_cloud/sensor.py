"""Platform for Kumo Cloud sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KumoCloudDataUpdateCoordinator, KumoCloudDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Kumo Cloud sensor devices."""
    coordinator: KumoCloudDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for zone in coordinator.zones:
        if "adapter" in zone and zone["adapter"]:
            device_serial = zone["adapter"]["deviceSerial"]
            zone_id = zone["id"]

            device = KumoCloudDevice(coordinator, zone_id, device_serial)
            entities.append(KumoCloudTemperatureSensor(device))
            entities.append(KumoCloudHumiditySensor(device))

    async_add_entities(entities)


class KumoCloudTemperatureSensor(SensorEntity):
    """Representation of a Kumo Cloud temperature sensor."""

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the temperature sensor."""
        self.device = device
        self._attr_name = f"{device.zone_data.get('name', 'Kumo Cloud')} Temperature"
        self._attr_unique_id = f"{device.device_serial}_temperature"
        # NOTE: native_unit_of_measurement = CELSIUS means HA uses standard math
        # (temp * 9/5 + 32) when displaying in Fahrenheit. This diverges from
        # Mitsubishi's proprietary F<->C lookup tables used by the climate entity
        # (see _c_to_f / _C_TO_F in climate.py). At certain values the two
        # entities will show different readings for the same underlying roomTemp:
        #   19.0 °C → sensor 66 °F (std) vs climate 67 °F (table)
        #   21.0 °C → sensor 70 °F (std) vs climate 69 °F (table)
        #   22.0 °C → sensor 72 °F (std) vs climate 71 °F (table)
        # Fixing this requires dropping native_unit_of_measurement and managing
        # the unit dynamically (matching hass.config.units.temperature_unit), which
        # also means sharing the lookup tables with this module — consider extracting
        # them to a shared temp_util.py. Deferred: impact is cosmetic/display-only.
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = "temperature"  # Explicitly define as a temperature sensor
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        adapter = self.device.zone_data.get("adapter", {})
        return adapter.get("roomTemp")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.device_serial)},
            name=self.device.zone_data.get("name", "Kumo Cloud Device"),
            manufacturer="Mitsubishi Electric",
        )


class KumoCloudHumiditySensor(SensorEntity):
    """Representation of a Kumo Cloud humidity sensor."""

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the humidity sensor."""
        self.device = device
        self._attr_name = f"{device.zone_data.get('name', 'Kumo Cloud')} Humidity"
        self._attr_unique_id = f"{device.device_serial}_humidity"
        self._attr_native_unit_of_measurement = "%"  # Use native unit
        self._attr_device_class = "humidity"  # Explicitly define as a humidity sensor
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the current humidity."""
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data
        return device_data.get("humidity", adapter.get("humidity"))

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.device_serial)},
            name=self.device.zone_data.get("name", "Kumo Cloud Device"),
            manufacturer="Mitsubishi Electric",
        )