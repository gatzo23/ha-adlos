"""Adlos Home Assistant Integration."""

import asyncio
import json
import logging
from aiohttp import web

from homeassistant.components import conversation, webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CHANNEL_NAME,
    CONF_PUBLIC_URL,
    CONF_SECRET_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_ADLOS_COMMAND,
)
from .notify import AdlosNotificationService

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
    
    # Message queue and active SSE subscriber responses for real-time delivery
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_WEBHOOK_ID: webhook_id,
        CONF_SECRET_TOKEN: secret_token,
        CONF_PUBLIC_URL: entry.data.get(CONF_PUBLIC_URL, ""),
        CONF_CHANNEL_NAME: entry.data.get(CONF_CHANNEL_NAME, "Adlos"),
        "subscribers": set(),
        "messages": [],
    }

    # Register direct action/service adlos.send_message
    async def async_handle_send_message(call: ServiceCall) -> None:
        """Handle adlos.send_message service call."""
        service = AdlosNotificationService(hass, entry.data)
        await service.async_send_message(
            message=call.data.get("message", ""),
            title=call.data.get("title"),
            target=call.data.get("target"),
            data=call.data.get("data", {}),
        )

    hass.services.async_register(DOMAIN, "send_message", async_handle_send_message)

    # Webhook handler: supports POST (Incoming Adlos -> HA), GET (SSE / Polling notifications HA -> Adlos), OPTIONS (CORS)
    async def async_handle_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        """Handle incoming webhook requests from Adlos."""
        # Handle CORS OPTIONS Preflight
        if request.method == "OPTIONS":
            return web.Response(
                status=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-Adlos-Token, Authorization",
                },
            )

        # Check Authentication Token
        provided_token = (
            request.headers.get("X-Adlos-Token")
            or request.query.get("token")
        )

        if request.method == "POST":
            try:
                data = await request.json()
            except Exception:
                return web.json_response({"error": "Invalid JSON"}, status=400)

            if not provided_token:
                provided_token = data.get("token")

            if provided_token != secret_token:
                _LOGGER.warning("Adlos webhook auth failed: invalid token")
                return web.json_response({"error": "Unauthorized"}, status=401)

            message = data.get("message", "").strip()
            sender = data.get("sender", "Adlos User")
            room = data.get("room") or data.get("target")

            _LOGGER.info("Received Adlos command from %s: %s", sender, message)

            # Process command via Home Assistant Conversation Engine
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
                response_text = f"Befehl '{message}' ausgeführt."

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
                },
                headers={"Access-Control-Allow-Origin": "*"},
            )

        elif request.method == "GET":
            # Real-Time SSE Stream or HTTP Polling for HA -> Adlos App
            if provided_token != secret_token:
                return web.json_response({"error": "Unauthorized"}, status=401)

            mode = request.query.get("mode", "poll")
            entry_store = hass.data[DOMAIN][entry.entry_id]

            if mode == "stream" or "text/event-stream" in request.headers.get("Accept", ""):
                # Server-Sent Events (SSE) Live Stream
                response = web.StreamResponse(
                    status=200,
                    reason="OK",
                    headers={
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
                await response.prepare(request)
                await response.write(b": ping\n\n")

                subscribers = entry_store["subscribers"]
                subscribers.add(response)

                try:
                    while not response.prepared:
                        await asyncio.sleep(15)
                        await response.write(b": ping\n\n")
                    # Keep connection alive until client disconnects
                    while True:
                        await asyncio.sleep(15)
                        await response.write(b": ping\n\n")
                except (asyncio.CancelledError, ConnectionResetError, Exception):
                    pass
                finally:
                    subscribers.discard(response)
                return response

            else:
                # HTTP Polling: return pending messages and clear queue
                messages = list(entry_store["messages"])
                entry_store["messages"].clear()
                return web.json_response(
                    {"messages": messages, "count": len(messages)},
                    headers={"Access-Control-Allow-Origin": "*"},
                )

        return web.json_response({"error": "Method Not Allowed"}, status=405)

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

    # Remove direct service
    hass.services.async_remove(DOMAIN, "send_message")

    # Unregister webhook
    webhook.async_unregister(hass, webhook_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
