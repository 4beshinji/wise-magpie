"""BlueZ D-Bus GATT service for wise-magpie.

Registers a BLE GATT application with BlueZ so that remote devices
(e.g. a smartphone) can send commands and receive responses over
Bluetooth Low Energy.

Requires the ``dbus-fast`` package (install with ``pip install wise-magpie[ble]``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

try:
    from dbus_fast import Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, dbus_property, method, signal as dbus_signal
except ImportError:
    raise SystemExit(
        "BLE support requires the 'dbus-fast' package.\n"
        "Install it with: pip install wise-magpie[ble]"
    )

from wise_magpie.ble.constants import (
    ADV_PATH,
    ADAPTER_IFACE,
    APP_PATH,
    BLUEZ_SERVICE,
    COMMAND_CHAR_PATH,
    COMMAND_CHAR_UUID,
    DBUS_OM_IFACE,
    GATT_MANAGER_IFACE,
    LE_ADV_MANAGER_IFACE,
    LOCAL_NAME,
    RESPONSE_CHAR_PATH,
    RESPONSE_CHAR_UUID,
    SERVICE_PATH,
    SERVICE_UUID,
    STATUS_CHAR_PATH,
    STATUS_CHAR_UUID,
)
from wise_magpie.ble.handler import dispatch, get_status_snapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# D-Bus interfaces for BlueZ GATT profile
# ---------------------------------------------------------------------------

class GattService(ServiceInterface):
    """org.bluez.GattService1 implementation."""

    def __init__(self) -> None:
        super().__init__("org.bluez.GattService1")

    @dbus_property()
    def UUID(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return SERVICE_UUID

    @dbus_property()
    def Primary(self) -> "b":  # type: ignore[valid-type]  # noqa: N802
        return True


class CommandCharacteristic(ServiceInterface):
    """Write-only characteristic that accepts JSON commands."""

    def __init__(self, on_write: Any) -> None:
        super().__init__("org.bluez.GattCharacteristic1")
        self._on_write = on_write

    @dbus_property()
    def UUID(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return COMMAND_CHAR_UUID

    @dbus_property()
    def Service(self) -> "o":  # type: ignore[valid-type]  # noqa: N802
        return SERVICE_PATH

    @dbus_property()
    def Flags(self) -> "as":  # type: ignore[valid-type]  # noqa: N802
        return ["write", "write-without-response"]

    @method()
    def WriteValue(self, value: "ay", options: "a{sv}") -> None:  # type: ignore[valid-type]  # noqa: N802
        data = bytes(value)
        logger.info("BLE command received: %d bytes", len(data))
        self._on_write(data)

    @method()
    def ReadValue(self, options: "a{sv}") -> "ay":  # type: ignore[valid-type]  # noqa: N802
        return []


class ResponseCharacteristic(ServiceInterface):
    """Read/Notify characteristic that returns command responses."""

    def __init__(self) -> None:
        super().__init__("org.bluez.GattCharacteristic1")
        self._value: bytes = b"{}"
        self._notifying = False

    def set_value(self, data: bytes) -> None:
        self._value = data

    @dbus_property()
    def UUID(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return RESPONSE_CHAR_UUID

    @dbus_property()
    def Service(self) -> "o":  # type: ignore[valid-type]  # noqa: N802
        return SERVICE_PATH

    @dbus_property()
    def Flags(self) -> "as":  # type: ignore[valid-type]  # noqa: N802
        return ["read", "notify"]

    @method()
    def ReadValue(self, options: "a{sv}") -> "ay":  # type: ignore[valid-type]  # noqa: N802
        return list(self._value)

    @method()
    def StartNotify(self) -> None:  # noqa: N802
        self._notifying = True
        logger.info("BLE notifications started on response characteristic")

    @method()
    def StopNotify(self) -> None:  # noqa: N802
        self._notifying = False
        logger.info("BLE notifications stopped on response characteristic")


class StatusCharacteristic(ServiceInterface):
    """Read-only characteristic returning current daemon status."""

    def __init__(self) -> None:
        super().__init__("org.bluez.GattCharacteristic1")

    @dbus_property()
    def UUID(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return STATUS_CHAR_UUID

    @dbus_property()
    def Service(self) -> "o":  # type: ignore[valid-type]  # noqa: N802
        return SERVICE_PATH

    @dbus_property()
    def Flags(self) -> "as":  # type: ignore[valid-type]  # noqa: N802
        return ["read"]

    @method()
    def ReadValue(self, options: "a{sv}") -> "ay":  # type: ignore[valid-type]  # noqa: N802
        return list(get_status_snapshot())


class ApplicationObjectManager(ServiceInterface):
    """org.freedesktop.DBus.ObjectManager — returns all managed GATT objects."""

    def __init__(self) -> None:
        super().__init__(DBUS_OM_IFACE)

    @method()
    def GetManagedObjects(self) -> "a{oa{sa{sv}}}":  # type: ignore[valid-type]  # noqa: N802
        return {
            SERVICE_PATH: {
                "org.bluez.GattService1": {
                    "UUID": Variant("s", SERVICE_UUID),
                    "Primary": Variant("b", True),
                },
            },
            COMMAND_CHAR_PATH: {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", COMMAND_CHAR_UUID),
                    "Service": Variant("o", SERVICE_PATH),
                    "Flags": Variant("as", ["write", "write-without-response"]),
                },
            },
            RESPONSE_CHAR_PATH: {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", RESPONSE_CHAR_UUID),
                    "Service": Variant("o", SERVICE_PATH),
                    "Flags": Variant("as", ["read", "notify"]),
                },
            },
            STATUS_CHAR_PATH: {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", STATUS_CHAR_UUID),
                    "Service": Variant("o", SERVICE_PATH),
                    "Flags": Variant("as", ["read"]),
                },
            },
        }


class LEAdvertisement(ServiceInterface):
    """org.bluez.LEAdvertisement1 — advertise the GATT service."""

    def __init__(self) -> None:
        super().__init__("org.bluez.LEAdvertisement1")

    @dbus_property()
    def Type(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return "peripheral"

    @dbus_property()
    def ServiceUUIDs(self) -> "as":  # type: ignore[valid-type]  # noqa: N802
        return [SERVICE_UUID]

    @dbus_property()
    def LocalName(self) -> "s":  # type: ignore[valid-type]  # noqa: N802
        return LOCAL_NAME

    @dbus_property()
    def Includes(self) -> "as":  # type: ignore[valid-type]  # noqa: N802
        return ["tx-power"]

    @method()
    def Release(self) -> None:  # noqa: N802
        logger.info("BLE advertisement released")


# ---------------------------------------------------------------------------
# Helper: find the default Bluetooth adapter
# ---------------------------------------------------------------------------

async def _find_adapter(bus: MessageBus) -> str:
    """Return the D-Bus object path of the first Bluetooth adapter."""
    introspection = await bus.introspect(BLUEZ_SERVICE, "/org/bluez")
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez", introspection)

    om = proxy.get_interface(DBUS_OM_IFACE)
    objects: dict = await om.call_get_managed_objects()

    for path, interfaces in objects.items():
        if GATT_MANAGER_IFACE in interfaces:
            return path

    raise RuntimeError("No Bluetooth adapter with GATT support found")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def _run(adapter_name: str | None = None) -> None:
    """Register the GATT application with BlueZ and run until interrupted."""
    bus = await MessageBus(bus_type=2).connect()  # system bus

    # Find adapter
    if adapter_name:
        adapter_path = f"/org/bluez/{adapter_name}"
    else:
        adapter_path = await _find_adapter(bus)
    logger.info("Using Bluetooth adapter: %s", adapter_path)

    # Build response characteristic so the command handler can update it
    response_char = ResponseCharacteristic()

    def on_command(data: bytes) -> None:
        result = dispatch(data)
        response_char.set_value(result)
        logger.info("BLE response set: %d bytes", len(result))

    # Export D-Bus objects
    command_char = CommandCharacteristic(on_write=on_command)
    status_char = StatusCharacteristic()
    gatt_service = GattService()
    obj_manager = ApplicationObjectManager()
    advertisement = LEAdvertisement()

    bus.export(APP_PATH, obj_manager)
    bus.export(SERVICE_PATH, gatt_service)
    bus.export(COMMAND_CHAR_PATH, command_char)
    bus.export(RESPONSE_CHAR_PATH, response_char)
    bus.export(STATUS_CHAR_PATH, status_char)
    bus.export(ADV_PATH, advertisement)

    # Get adapter proxy for GATT and advertising managers
    introspection = await bus.introspect(BLUEZ_SERVICE, adapter_path)
    adapter_proxy = bus.get_proxy_object(BLUEZ_SERVICE, adapter_path, introspection)

    # Register GATT application
    gatt_manager = adapter_proxy.get_interface(GATT_MANAGER_IFACE)
    await gatt_manager.call_register_application(APP_PATH, {})
    logger.info("GATT application registered")

    # Register advertisement
    try:
        adv_manager = adapter_proxy.get_interface(LE_ADV_MANAGER_IFACE)
        await adv_manager.call_register_advertisement(ADV_PATH, {})
        logger.info("BLE advertisement registered")
    except Exception:  # noqa: BLE001
        logger.warning("Could not register BLE advertisement (non-fatal)")

    logger.info(
        "wise-magpie BLE GATT service running (service UUID: %s)", SERVICE_UUID
    )

    # Run until interrupted
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await stop_event.wait()

    # Cleanup
    try:
        await gatt_manager.call_unregister_application(APP_PATH)
    except Exception:  # noqa: BLE001
        pass
    logger.info("GATT service stopped")
    bus.disconnect()


def serve(adapter: str | None = None) -> None:
    """Start the BLE GATT service (blocking).

    Parameters
    ----------
    adapter:
        Bluetooth adapter name (e.g. ``hci0``). Auto-detected if ``None``.
    """
    asyncio.run(_run(adapter))
