"""BLE GATT service UUIDs and constants."""

# Custom 128-bit UUIDs for the wise-magpie GATT service.
# Base: a1b2c3d4-e5f6-7890-abcd-ef12345678xx
SERVICE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567800"
COMMAND_CHAR_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567801"
RESPONSE_CHAR_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567802"
STATUS_CHAR_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567803"

# BlueZ D-Bus constants
BLUEZ_SERVICE = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADV_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

# D-Bus object paths for our application
APP_PATH = "/org/wisemagpie"
SERVICE_PATH = f"{APP_PATH}/service0"
COMMAND_CHAR_PATH = f"{SERVICE_PATH}/char0"
RESPONSE_CHAR_PATH = f"{SERVICE_PATH}/char1"
STATUS_CHAR_PATH = f"{SERVICE_PATH}/char2"
ADV_PATH = f"{APP_PATH}/advertisement0"

# BLE advertisement
LOCAL_NAME = "wise-magpie"
