"""Adlos notification service & entity platform."""

import asyncio
import json
import logging
import os
import secrets
import time
import aiohttp

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
    BaseNotificationService,
    NotifyEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_CAMERA,
    ATTR_IMAGE,
    ATTR_PHOTO,
    ATTR_VIDEO,
    CONF_CHANNEL_NAME,
    CONF_PUBLIC_URL,
    CONF_SECRET_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Adlos notify entity from a config entry."""
    async_add_entities([AdlosNotifyEntity(hass, entry)], update_before_add=True)


class AdlosNotifyEntity(NotifyEntity):
    """Adlos Notify Entity for modern Home Assistant UI."""

    _attr_has_entity_name = False
    _attr_name = "adlos"
    _attr_icon = "mdi:chat-processing-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the notify entity."""
        self.hass = hass
        self.entry = entry
        self.entity_id = "notify.adlos"
        self._attr_unique_id = f"{DOMAIN}_notify_{entry.entry_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data.get(CONF_CHANNEL_NAME, "Adlos"),
            "manufacturer": "Adlos",
            "model": "Messaging Integration",
            "entry_type": "service",
        }
        self.public_url = entry.data.get(CONF_PUBLIC_URL, "")
        self.webhook_id = entry.data.get(CONF_WEBHOOK_ID, "")
        self.secret_token = entry.data.get(CONF_SECRET_TOKEN, "")

    async def async_send_message(self, message: str, title: str | None = None, data: dict | None = None) -> None:
        """Send a notification message via Adlos Notify Entity."""
        service = AdlosNotificationService(self.hass, self.entry.data)
        await service.async_send_message(message=message, title=title, data=data)


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType = None,
) -> BaseNotificationService:
    """Get legacy Adlos notification service."""
    if discovery_info is None:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Adlos config entries found")
            return None
        entry_data = entries[0].data
    else:
        entry_data = discovery_info

    return AdlosNotificationService(hass, entry_data)


class AdlosNotificationService(BaseNotificationService):
    """Implementation of the Adlos notification service."""

    def __init__(self, hass: HomeAssistant, entry_data: dict):
        """Initialize the service."""
        self.hass = hass
        self.entry_id = entry_data.get("entry_id", "") if isinstance(entry_data, dict) else ""
        self.public_url = entry_data.get(CONF_PUBLIC_URL, "") if isinstance(entry_data, dict) else ""
        self.webhook_id = entry_data.get(CONF_WEBHOOK_ID, "") if isinstance(entry_data, dict) else ""
        self.secret_token = entry_data.get(CONF_SECRET_TOKEN, "") if isinstance(entry_data, dict) else ""

    async def async_send_message(self, message: str = "", **kwargs) -> None:
        """Send a notification message to Adlos via REST API."""
        title = kwargs.get(ATTR_TITLE) or kwargs.get("title")
        targets = kwargs.get(ATTR_TARGET) or kwargs.get("target") or kwargs.get("targets")
        data = kwargs.get(ATTR_DATA) or kwargs.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        extra_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        # Normalize targets
        if targets is None:
            targets = data.get("target") or data.get("targets") or extra_data.get("target") or extra_data.get("targets")

        target_list = None
        if isinstance(targets, str):
            target_list = [targets]
        elif isinstance(targets, list):
            target_list = [str(t) for t in targets]

        # 1. Room-ID & Targets: default room is always "homeassistant_bot" unless explicitly set in data.room
        room_id = data.get("room") or extra_data.get("room") or "homeassistant_bot"

        # 3. Unique Message-ID & Timestamp
        msg_id = f"ha_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

        payload = {
            "id": msg_id,
            "room": room_id,
            "sender": "Home Assistant",
            "type": "text",
            "title": title or "Home Assistant",
            "message": message,
            "text": message,
            "body": message,
            "targets": target_list,
            "target": targets,
            "token": self.secret_token,
            "webhook_id": self.webhook_id,
            "timestamp": time.time(),
        }

        # 2. Lightweight image handling for SSE stream (no large Base64)
        camera_entity = data.get(ATTR_CAMERA) or data.get("camera") or extra_data.get("camera")
        image_path_or_url = (
            data.get(ATTR_IMAGE)
            or data.get(ATTR_PHOTO)
            or data.get("image")
            or data.get("photo")
            or data.get("path")
            or data.get("file_path")
            or data.get("file")
            or extra_data.get("image")
            or extra_data.get("photo")
            or extra_data.get("path")
            or extra_data.get("file_path")
            or extra_data.get("file")
        )
        video_path_or_url = data.get(ATTR_VIDEO) or data.get("video") or extra_data.get("video")

        if camera_entity:
            proxy_url = f"/api/camera_proxy/{camera_entity}"
            payload["type"] = "image"
            payload["image"] = proxy_url
            payload["attachment"] = {
                "type": "image",
                "url": proxy_url,
                "camera": camera_entity,
            }
        elif image_path_or_url and isinstance(image_path_or_url, str):
            payload["type"] = "image"
            payload["image"] = image_path_or_url
            payload["attachment"] = {
                "type": "image",
                "url": image_path_or_url,
            }
        elif video_path_or_url and isinstance(video_path_or_url, str):
            payload["type"] = "video"
            payload["video"] = video_path_or_url
            payload["attachment"] = {
                "type": "video",
                "url": video_path_or_url,
            }

        if "actions" in data:
            payload["actions"] = data["actions"]
        elif "actions" in extra_data:
            payload["actions"] = extra_data["actions"]

        # 1. Fire HA event for local notification listeners or websockets
        self.hass.bus.async_fire("adlos_notification_sent", payload)

        # 2. Add to in-memory queue & broadcast to SSE subscribers for real-time delivery to Adlos App
        target_entry_id = getattr(self, "entry_id", None)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if not target_entry_id or entry.entry_id == target_entry_id:
                store = self.hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
                if "messages" in store:
                    store["messages"].append(payload)
                    if len(store["messages"]) > 50:
                        store["messages"].pop(0)

                    # Real-time SSE broadcast
                    subscribers = list(store.get("subscribers", []))
                    if subscribers:
                        sse_data = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                        for resp in subscribers:
                            try:
                                asyncio.create_task(resp.write(sse_data))
                            except Exception as err:
                                _LOGGER.debug("Error writing to SSE subscriber: %s", err)

        # 3. Post REST payload directly to configured PocketBase / REST push gateway endpoint
        session = async_get_clientsession(self.hass)
        raw_base_url = (self.public_url or "").strip()

        if not raw_base_url:
            _LOGGER.debug("ADLOS_REST: No public_url configured, skipping REST post")
            return

        if "records" in raw_base_url:
            target_url = raw_base_url
        elif raw_base_url.startswith(("http://", "https://")):
            target_url = f"{raw_base_url.rstrip('/')}/api/collections/messages/records"
        else:
            target_url = f"https://{raw_base_url.rstrip('/')}/api/collections/messages/records"

        candidate_urls = [target_url]

        headers = {}
        if self.secret_token:
            headers["Authorization"] = f"Bearer {self.secret_token}"

        success = False

        # If local image file exists, post via FormData multipart file upload
        if image_path_or_url and isinstance(image_path_or_url, str) and os.path.exists(image_path_or_url):
            text_val = f"{title}\n{message}" if title else message
            _LOGGER.debug("ADLOS_REST: Sending photo to %s (room=%s, file=%s): %s", target_url, room_id, image_path_or_url, text_val)

            try:
                def _read_img_sync(path):
                    with open(path, "rb") as f:
                        return f.read()

                img_bytes = await self.hass.async_add_executor_job(_read_img_sync, image_path_or_url)

                for url in candidate_urls:
                    try:
                        form_data = aiohttp.FormData()
                        form_data.add_field("text", text_val)
                        form_data.add_field("sender", "Home Assistant")
                        form_data.add_field("room", room_id)
                        form_data.add_field("type", "image")
                        form_data.add_field("file", img_bytes, filename=os.path.basename(image_path_or_url))

                        async with session.post(url, data=form_data, headers=headers, timeout=15) as resp:
                            resp_body = await resp.text()
                            if resp.status in (200, 201, 204):
                                _LOGGER.debug("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", resp.status, url, resp_body)
                                success = True
                                break
                            else:
                                _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", resp.status, url, resp_body)
                    except Exception as err:
                        _LOGGER.error("ADLOS_REST EXCEPTION posting photo to %s: %s", url, err)
            except Exception as err:
                _LOGGER.error("ADLOS_REST: Failed reading image file %s: %s", image_path_or_url, err)
        else:
            headers["Content-Type"] = "application/json"
            _LOGGER.debug("ADLOS_REST: Sending message to %s (room=%s): %s", target_url, room_id, message)

            for url in candidate_urls:
                try:
                    async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
                        resp_body = await resp.text()
                        if resp.status in (200, 201, 204):
                            _LOGGER.debug("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", resp.status, url, resp_body)
                            success = True
                            break
                        else:
                            _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", resp.status, url, resp_body)
                except Exception as err:
                    _LOGGER.error("ADLOS_REST EXCEPTION posting to %s: %s", url, err)

        if not success:
            _LOGGER.error("ADLOS_REST: Failed to post message to: %s", candidate_urls)
