"""Constants for the Growatt Web integration."""

from datetime import timedelta

DOMAIN = "growatt_web"

# Poll intervals in minutes, set in the integration options.
# Growatt allows one call per endpoint every 5 minutes.
CONF_LIVE_INTERVAL = "live_interval"
CONF_SETTINGS_INTERVAL = "settings_interval"
DEFAULT_LIVE_INTERVAL = 10
DEFAULT_SETTINGS_INTERVAL = 60
LIVE_INTERVAL_RANGE = (5, 60)
SETTINGS_INTERVAL_RANGE = (30, 24 * 60)


def live_interval(options: dict) -> timedelta:
    return timedelta(minutes=options.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL))


def settings_interval_seconds(options: dict) -> int:
    return 60 * options.get(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL)

CONF_PLANT_ID = "plant_id"
CONF_SERIAL = "serial"
CONF_MODEL = "model"
CONF_API_TOKEN = "api_token"
