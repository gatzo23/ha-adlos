"""Adlos Home Assistant Integration."""

import logging
from aiohttp import web

from homeassistant.components import conversation, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CHANNEL_NAME,
    CONF_PUBLIC_URL,
    CONF_SECRET_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_ADLOS_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["notify"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Adlos component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Adlos from a config entry."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    secret_token = entry.data[CONF_SECRET_TOKEN]

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_WEBHOOK_ID: webhook_id,
        CONF_SECRET_TOKEN: secret_token,
        CONF_PUBLIC_URL: entry.data.get(CONF_PUBLIC_URL, ""),
        CONF_CHANNEL_NAME: entry.data.get(CONF_CHANNEL_NAME, "Adlos"),
    }

    # Register webhook for two-way communication (Adlos App -> Home Assistant)
    async def async_handle_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        """Handle incoming webhook requests from Adlos."""
        try:
            data = await request.json()
        except Exception:
            _LOGGER.warning("Adlos webhook received invalid JSON payload")
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # Authenticate token
        provided_token = data.get("token") or request.headers.get("X-Adlos-Token") or request.query.get("token")
        if provided_token != secret_token:
            _LOGGER.warning("Adlos webhook authentication failed: invalid token")
            return web.json_response({"error": "Unauthorized"}, status=401)

        message = data.get("message", "").strip()
        sender = data.get("sender", "Adlos User")
        room = data.get("room") or data.get("target")

        _LOGGER.info("Received Adlos command from %s: %s", sender, message)

        # Process command using Home Assistant's Conversation / Intent engine
        response_text = ""
        if message:
            try:
                converse_result = await conversation.async_converse(
                    hass=hass,
                    text=message,
                    conversation_id=f"adlos_{sender}",
                    context=None,
                    language=hass.config.language,
                )
                if (
                    converse_result
                    and converse_result.response
                    and converse_result.response.speech
                    and "plain" in converse_result.response.speech
                ):
                    response_text = converse_result.response.speech["plain"].get("speech", "")
            except Exception as err:
                _LOGGER.error("Error processing conversation for Adlos command: %s", err)
                response_text = f"Befehl erhalten, konnte aber nicht verarbeitet werden: {err}"

        if not response_text:
            response_text = f"Befehl '{message}' wurde in Home Assistant ausgeführt."

        # Fire HA event for custom user automations
        hass.bus.async_fire(
            EVENT_ADLOS_COMMAND,
            {
                "message": message,
                "sender": sender,
                "room": room,
                "response": response_text,
                "webhook_id": webhook_id,
            },
        )

        return web.json_response(
            {
                "status": "ok",
                "response": response_text,
                "received_message": message,
            }
        )

    # Register Webhook with HA Webhook component
    webhook.async_register(
        hass,
        DOMAIN,
        "Adlos Integration",
        webhook_id,
        async_handle_webhook,
    )
    _LOGGER.info("Registered Adlos webhook endpoint: /api/webhook/%s", webhook_id)

    # Setup notify platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Adlos config entry."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    # Unregister webhook
    webhook.async_unregister(hass, webhook_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
