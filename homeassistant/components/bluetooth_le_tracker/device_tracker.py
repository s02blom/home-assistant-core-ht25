"""Tracking for bluetooth low energy devices."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from uuid import UUID

from bleak import BleakClient, BleakError
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.components.device_tracker import (
    CONF_TRACK_NEW,
    PLATFORM_SCHEMA as DEVICE_TRACKER_PLATFORM_SCHEMA,
    SCAN_INTERVAL,
    SourceType,
)
from homeassistant.components.device_tracker.legacy import (
    YAML_DEVICES,
    AsyncSeeCallback,
    async_load_config,
)
from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Base UUID: 00000000-0000-1000-8000-00805F9B34FB
# Battery characteristic: 0x2a19 (https://www.bluetooth.com/specifications/gatt/characteristics/)
BATTERY_CHARACTERISTIC_UUID = UUID("00002a19-0000-1000-8000-00805f9b34fb")
CONF_TRACK_BATTERY = "track_battery"
CONF_TRACK_BATTERY_INTERVAL = "track_battery_interval"
DEFAULT_TRACK_BATTERY_INTERVAL = timedelta(days=1)
DATA_BLE = "BLE"
DATA_BLE_ADAPTER = "ADAPTER"
BLE_PREFIX = "BLE_"
MIN_SEEN_NEW = 5

PLATFORM_SCHEMA = DEVICE_TRACKER_PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_TRACK_BATTERY, default=False): cv.boolean,
        vol.Optional(
            CONF_TRACK_BATTERY_INTERVAL, default=DEFAULT_TRACK_BATTERY_INTERVAL
        ): cv.time_period,
    }
)


class BLEDeviceTracker:
    """Manages Bluetooth LE device tracking."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_see: AsyncSeeCallback,
        battery_track_interval: timedelta,
        track_new: bool,
    ) -> None:
        """Initialize the BLE device tracker."""
        self.hass = hass
        self.async_see = async_see
        self.battery_track_interval = battery_track_interval
        self.track_new = track_new

        self.new_devices: dict[str, dict] = {}
        self.devs_to_track: set[str] = set()
        self.devs_no_track: set[str] = set()
        self.devs_advertise_time: dict[str, float] = {}
        self.devs_track_battery: dict[str, datetime] = {}

    async def async_see_device(
        self,
        address: str,
        name: str | None,
        new_device: bool = False,
        battery: int | None = None,
    ) -> None:
        """Mark a device as seen."""
        if name is not None:
            name = name.strip("\x00")

        if new_device:
            should_continue, name = await self._handle_new_device(address, name)
            if not should_continue:
                return

        await self.async_see(
            mac=BLE_PREFIX + address,
            host_name=name,
            source_type=SourceType.BLUETOOTH_LE,
            battery=battery,
        )

    async def _handle_new_device(
        self, address: str, name: str | None
    ) -> tuple[bool, str | None]:
        """Handle a newly discovered device.

        Returns a tuple of (should_continue, name_to_use).
        """
        if address in self.new_devices:
            self.new_devices[address]["seen"] += 1
            if name:
                self.new_devices[address]["name"] = name
            else:
                # Preserve the name from the previous scan
                name = self.new_devices[address]["name"]
            _LOGGER.debug(
                "Seen %s %s times", address, self.new_devices[address]["seen"]
            )

            if self.new_devices[address]["seen"] < MIN_SEEN_NEW:
                return False, name

            _LOGGER.debug("Adding %s to tracked devices", address)
            self.add_device_to_track(address)
            return True, name

        _LOGGER.debug("Seen %s for the first time", address)
        self.new_devices[address] = {"seen": 1, "name": name}
        return False, name

    def add_device_to_track(self, address: str) -> None:
        """Add a device to the tracking list."""
        self.devs_to_track.add(address)
        if self.battery_track_interval > timedelta(0):
            self.devs_track_battery[address] = dt_util.as_utc(datetime.fromtimestamp(0))

    async def async_update_ble_battery(
        self,
        mac: str,
        now: datetime,
        service_info: bluetooth.BluetoothServiceInfoBleak,
    ) -> None:
        """Lookup Bluetooth LE devices and update battery status."""
        device = self._get_connectable_device(service_info)
        if device is None:
            return

        battery = await self._read_battery_level(device, service_info.name, mac)
        if battery:
            await self.async_see_device(mac, service_info.name, battery=battery)

    def _get_connectable_device(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ):
        """Get a connectable device from service info."""
        if service_info.connectable:
            return service_info.device

        connectable_device = bluetooth.async_ble_device_from_address(
            self.hass, service_info.device.address, True
        )
        if connectable_device:
            return connectable_device

        # The device can be seen by a passive tracker but we
        # don't have a route to make a connection
        return None

    async def _read_battery_level(
        self, device, device_name: str, mac: str
    ) -> int | None:
        """Read battery level from a BLE device."""
        try:
            async with BleakClient(device) as client:
                bat_char = await client.read_gatt_char(BATTERY_CHARACTERISTIC_UUID)
                return ord(bat_char)
        except TimeoutError:
            _LOGGER.debug(
                "Timeout when trying to get battery status for %s", device_name
            )
        except (AttributeError, BleakError) as err:
            _LOGGER.debug("Could not read battery status: %s", err)
            # If the device does not offer battery information, there is no point in asking again later on.
            # Remove the device from the battery-tracked devices, so that their battery is not wasted
            # trying to get an unavailable information.
            if mac in self.devs_track_battery:
                del self.devs_track_battery[mac]
        return None

    @callback
    def async_update_ble(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a ble callback."""
        mac = service_info.address

        if mac in self.devs_to_track:
            self._handle_tracked_device(mac, service_info)

        if (
            self.track_new
            and mac not in self.devs_to_track
            and mac not in self.devs_no_track
        ):
            self._handle_discovered_device(mac, service_info)

    def _handle_tracked_device(
        self, mac: str, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Handle updates for a tracked device."""
        self.devs_advertise_time[mac] = service_info.time
        now = dt_util.utcnow()
        self.hass.async_create_task(self.async_see_device(mac, service_info.name))

        if self._should_update_battery(mac, now):
            self.devs_track_battery[mac] = now
            self.hass.async_create_background_task(
                self.async_update_ble_battery(mac, now, service_info),
                "bluetooth_le_tracker.device_tracker-see_update_ble_battery",
            )

    def _should_update_battery(self, mac: str, now: datetime) -> bool:
        """Check if battery should be updated for a device."""
        return (
            mac in self.devs_track_battery
            and now > self.devs_track_battery[mac] + self.battery_track_interval
        )

    def _handle_discovered_device(
        self, mac: str, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        """Handle a newly discovered device."""
        _LOGGER.debug("Discovered Bluetooth LE device %s", mac)
        self.hass.async_create_task(
            self.async_see_device(mac, service_info.name, new_device=True)
        )

    @callback
    def async_refresh_ble(self, now: datetime) -> None:
        """Refresh BLE devices from the discovered service info."""
        # Make sure devices are seen again at the scheduled
        # interval so they do not get set to not_home when
        # there have been no callbacks because the RSSI or
        # other properties have not changed.
        for service_info in bluetooth.async_discovered_service_info(self.hass, False):
            # Only call async_update_ble if the advertisement time has changed
            if service_info.time != self.devs_advertise_time.get(service_info.address):
                self.async_update_ble(
                    service_info, bluetooth.BluetoothChange.ADVERTISEMENT
                )


async def _load_known_devices(
    yaml_path: str,
    hass: HomeAssistant,
    tracker: BLEDeviceTracker,
) -> None:
    """Load all known devices from configuration."""
    for device in await async_load_config(yaml_path, hass, timedelta(0)):
        if not device.mac or device.mac[:4].upper() != BLE_PREFIX:
            continue

        address = device.mac[4:]
        if device.track:
            _LOGGER.debug("Adding %s to BLE tracker", device.mac)
            tracker.add_device_to_track(address)
        else:
            _LOGGER.debug("Adding %s to BLE do not track", device.mac)
            tracker.devs_no_track.add(address)


async def async_setup_scanner(
    hass: HomeAssistant,
    config: ConfigType,
    async_see: AsyncSeeCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> bool:
    """Set up the Bluetooth LE Scanner."""
    battery_track_interval = (
        config[CONF_TRACK_BATTERY_INTERVAL]
        if config[CONF_TRACK_BATTERY]
        else timedelta(0)
    )
    track_new = bool(config.get(CONF_TRACK_NEW))
    interval: timedelta = config.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL)

    tracker = BLEDeviceTracker(hass, async_see, battery_track_interval, track_new)

    # Load all known devices
    yaml_path = hass.config.path(YAML_DEVICES)
    await _load_known_devices(yaml_path, hass, tracker)

    if not tracker.devs_to_track and not track_new:
        _LOGGER.warning("No Bluetooth LE devices to track!")
        return False

    # Register callbacks
    cancels = [
        bluetooth.async_register_callback(
            hass,
            tracker.async_update_ble,
            BluetoothCallbackMatcher(connectable=False),
            bluetooth.BluetoothScanningMode.ACTIVE,
        ),
        async_track_time_interval(hass, tracker.async_refresh_ble, interval),
    ]

    @callback
    def _async_handle_stop(event: Event) -> None:
        """Cancel the callback."""
        for cancel in cancels:
            cancel()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_handle_stop)

    tracker.async_refresh_ble(dt_util.now())

    return True
