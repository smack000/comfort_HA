from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .api import KumoCloudAPI, KumoCloudAuthError, KumoCloudConnectionError
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, LOG_VERSION


class _VersionedLogger(logging.LoggerAdapter):
    """Logger adapter that prepends the log version to every message."""

    def process(self, msg, kwargs):
        return f"[v{LOG_VERSION}] {msg}", kwargs


_LOGGER = _VersionedLogger(logging.getLogger(__name__))

class KumoCloudDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Kumo Cloud data."""

    def __init__(self, hass: HomeAssistant, api: KumoCloudAPI, site_id: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.site_id = site_id
        self.zones: list[dict[str, Any]] = []
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_profiles: dict[str, list[dict[str, Any]]] = {}

        # Instance variable to store cached commands
        self.cached_commands: dict[tuple[str, str], tuple[str, Any]] = {}

    def _process_pending_commands(self, device_serial: str, device_detail: dict[str, Any]) -> None:
        """Process cached commands and cull outdated commands for a device."""
        self.cull_cached_commands(device_serial)

        # Reapply cached commands to the device details
        for (cached_device_serial, command), (_, command_value) in self.cached_commands.items():
            if cached_device_serial == device_serial:
                device_detail[command] = command_value

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Kumo Cloud."""
        try:
            # Get zones for the site
            zones = await self.api.get_zones(self.site_id)

            # Get device details for each zone
            devices = {}
            device_profiles = {}

            for zone in zones:
                if "adapter" in zone and zone["adapter"]:
                    device_serial = zone["adapter"]["deviceSerial"]

                    # Get device details and profile in parallel
                    device_detail_task = self.api.get_device_details(device_serial)
                    device_profile_task = self.api.get_device_profile(device_serial)

                    device_detail, device_profile = await asyncio.gather(
                        device_detail_task, device_profile_task
                    )

                    # Process pending commands for the device
                    self._process_pending_commands(device_serial, device_detail)

                    devices[device_serial] = device_detail
                    device_profiles[device_serial] = device_profile

                    _LOGGER.debug(
                        "Device details fetched for %s: roomTemp=%s, spHeat=%s, spCool=%s, "
                        "operationMode=%s, power=%s, fanSpeed=%s, airDirection=%s, humidity=%s",
                        device_serial,
                        device_detail.get("roomTemp"),
                        device_detail.get("spHeat"),
                        device_detail.get("spCool"),
                        device_detail.get("operationMode"),
                        device_detail.get("power"),
                        device_detail.get("fanSpeed"),
                        device_detail.get("airDirection"),
                        device_detail.get("humidity"),
                    )

            # Store the data for access by entities
            self.zones = zones
            self.devices = devices
            self.device_profiles = device_profiles

            return {
                "zones": zones,
                "devices": devices,
                "device_profiles": device_profiles,
            }

        except KumoCloudAuthError as err:
            # Try to refresh token once
            try:
                await self.api.refresh_access_token()
                # Retry the request
                return await self._async_update_data()
            except KumoCloudAuthError as refresh_err:
                raise UpdateFailed(
                    f"Authentication failed: {refresh_err}"
                ) from refresh_err
        except KumoCloudConnectionError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_refresh_device(self, device_serial: str) -> None:
        """Refresh a specific device's data immediately."""
        try:
            # Get fresh device details
            device_detail = await self.api.get_device_details(device_serial)

            _LOGGER.debug(
                "Raw cloud data for %s (before pending commands): roomTemp=%s, spHeat=%s, spCool=%s, "
                "operationMode=%s, power=%s, fanSpeed=%s, airDirection=%s, humidity=%s",
                device_serial,
                device_detail.get("roomTemp"),
                device_detail.get("spHeat"),
                device_detail.get("spCool"),
                device_detail.get("operationMode"),
                device_detail.get("power"),
                device_detail.get("fanSpeed"),
                device_detail.get("airDirection"),
                device_detail.get("humidity"),
            )

            # Process pending commands for the device
            self._process_pending_commands(device_serial, device_detail)

            _LOGGER.debug(
                "Device details for %s (after pending commands): roomTemp=%s, spHeat=%s, spCool=%s, "
                "operationMode=%s, power=%s, fanSpeed=%s, airDirection=%s, humidity=%s",
                device_serial,
                device_detail.get("roomTemp"),
                device_detail.get("spHeat"),
                device_detail.get("spCool"),
                device_detail.get("operationMode"),
                device_detail.get("power"),
                device_detail.get("fanSpeed"),
                device_detail.get("airDirection"),
                device_detail.get("humidity"),
            )

            # Update the cached device data
            self.devices[device_serial] = device_detail

            # Also update the zone data if it contains the same info
            for zone in self.zones:
                if "adapter" in zone and zone["adapter"]:
                    if zone["adapter"]["deviceSerial"] == device_serial:
                        # Update adapter data with fresh device data
                        zone["adapter"].update(
                            {
                                "roomTemp": device_detail.get("roomTemp"),
                                "operationMode": device_detail.get("operationMode"),
                                "power": device_detail.get("power"),
                                "fanSpeed": device_detail.get("fanSpeed"),
                                "airDirection": device_detail.get("airDirection"),
                                "spCool": device_detail.get("spCool"),
                                "spHeat": device_detail.get("spHeat"),
                                "humidity": device_detail.get("humidity"),
                            }
                        )
                        break

            # Update the coordinator's data dict
            self.data = {
                "zones": self.zones,
                "devices": self.devices,
                "device_profiles": self.device_profiles,
            }

            # Notify all listeners that data has been updated
            self.async_update_listeners()

            _LOGGER.debug("Refreshed device %s data", device_serial)

        except Exception as err:
            _LOGGER.warning("Failed to refresh device %s: %s", device_serial, err)

    def cache_command(self, device_serial: str, command: str, value: Any) -> None:
        """Cache a command with its value and timestamp.

        Cached commands are used for optimistic UI updates: after we send a
        command the Kumo Cloud API may take an indeterminate amount of time to
        reflect the new value in subsequent GET responses.  By storing the
        sent value here and re-applying it over the polled data in
        _process_pending_commands(), the UI immediately shows what the user
        asked for rather than snapping back to the stale cloud value.  Entries
        are evicted by cull_cached_commands() once they exceed the 60-second
        TTL, by which point the cloud should have caught up.
        """
        current_time = datetime.now(timezone.utc).isoformat()
        self.cached_commands[(device_serial, command)] = (current_time, value)
        _LOGGER.debug(
            "Cached command for device %s: %s=%s (cached_at=%s)",
            device_serial, command, value, current_time
        )

    def cull_cached_commands(self, device_serial: str) -> None:
        """Remove cached commands for a device that have exceeded the 60-second TTL."""
        to_remove = []
        now = datetime.now(timezone.utc)

        for key, value in self.cached_commands.items():
            cached_device_serial, command = key
            cached_date, _ = value
            cached_date_obj = datetime.fromisoformat(cached_date)
            age = (now - cached_date_obj).total_seconds()

            if cached_device_serial == device_serial and age >= 60:
                _LOGGER.debug(
                    "Evicting cached command %s for device %s (TTL expired, age=%.1fs)",
                    command, cached_device_serial, age,
                )
                to_remove.append(key)

        for key in to_remove:
            del self.cached_commands[key]

        if to_remove:
            _LOGGER.debug(
                "Culled %d TTL-expired cached commands for device %s. Remaining: %d",
                len(to_remove), device_serial, len(self.cached_commands)
            )

class KumoCloudDevice:
    """Representation of a Kumo Cloud device."""

    def __init__(
        self,
        coordinator: KumoCloudDataUpdateCoordinator,
        zone_id: str,
        device_serial: str,
    ) -> None:
        """Initialize the device."""
        self.coordinator = coordinator
        self.zone_id = zone_id
        self.device_serial = device_serial
        self._zone_data: dict[str, Any] | None = None
        self._device_data: dict[str, Any] | None = None
        self._profile_data: list[dict[str, Any]] | None = None
        self._send_lock = asyncio.Lock()
        self._pending_commands: dict[str, Any] | None = None

    @property
    def zone_data(self) -> dict[str, Any]:
        """Get the zone data."""
        # Always get fresh data from coordinator
        for zone in self.coordinator.zones:
            if zone["id"] == self.zone_id:
                return zone
        return {}

    @property
    def device_data(self) -> dict[str, Any]:
        """Get the device data."""
        # Always get fresh data from coordinator
        return self.coordinator.devices.get(self.device_serial, {})

    @property
    def profile_data(self) -> list[dict[str, Any]]:
        """Get the device profile data."""
        # Always get fresh data from coordinator
        return self.coordinator.device_profiles.get(self.device_serial, [])

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        adapter = self.zone_data.get("adapter", {})
        device_data = self.device_data

        # Check both adapter and device data for connection status
        adapter_connected = adapter.get("connected", False)
        device_connected = device_data.get("connected", adapter_connected)

        return device_connected

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.zone_data.get("name", f"Zone {self.zone_id}")

    @property
    def unique_id(self) -> str:
        """Return a unique ID for the device."""
        return f"{self.device_serial}_{self.zone_id}"

    async def send_command(self, commands: dict[str, Any]) -> None:
        """Send a command to the device.

        Enforces two rate-limiting guarantees:

        1. **Serialization** — only one API call is in-flight at a time per
           device.  If a second command arrives while one is already being sent,
           it is held in a last-write-wins pending slot (_pending_commands) and
           dispatched automatically once the in-flight call completes.

        2. **Minimum inter-send gap** — after each send completes (including the
           1-second settle sleep and a device refresh), a further delay is
           inserted so that consecutive sends are always at least 5 seconds
           apart.  This prevents the Kumo Cloud API from receiving rapid-fire
           commands that it may silently drop or apply out of order.
        """
        if self._send_lock.locked():
            if self._pending_commands is None:
                self._pending_commands = {}
            self._pending_commands.update(commands)
            _LOGGER.debug(
                "Command queued for device %s (in-flight): %s", self.device_serial, commands
            )
            return

        async with self._send_lock:
            to_send = commands
            while True:
                sent_at = asyncio.get_event_loop().time()
                try:
                    response = await self.coordinator.api.send_command(self.device_serial, to_send)
                    _LOGGER.debug(
                        "Sent command to device %s: %s, Response: %s",
                        self.device_serial, to_send, response,
                    )

                    # Wait a moment for the command to be processed
                    await asyncio.sleep(1)

                    # Refresh this specific device's data immediately
                    await self.coordinator.async_refresh_device(self.device_serial)

                except Exception as err:
                    _LOGGER.error(
                        "Failed to send command to device %s: %s", self.device_serial, err
                    )
                    raise

                to_send = self._pending_commands
                self._pending_commands = None
                if to_send is None:
                    break

                # Enforce a minimum 5-second gap between sends; the 1s sleep +
                # refresh above already count toward this.
                remaining = 5.0 - (asyncio.get_event_loop().time() - sent_at)
                if remaining > 0:
                    _LOGGER.debug(
                        "Rate limiting device %s: waiting %.1fs before next command",
                        self.device_serial, remaining,
                    )
                    await asyncio.sleep(remaining)

                _LOGGER.debug(
                    "Sending queued command for device %s: %s", self.device_serial, to_send
                )

    def cache_command(self, command: str, value: Any) -> None:
        """Cache a command with its value and timestamp in the coordinator."""
        self.coordinator.cache_command(self.device_serial, command, value)

    def cache_commands(self, commands: dict[str, Any]) -> None:
        """Cache multiple commands with their values and timestamps in the coordinator."""
        for command, value in commands.items():
            self.cache_command(command, value)