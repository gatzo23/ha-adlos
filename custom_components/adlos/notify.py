"""Adlos notification service & entity platform."""

import asyncio
import base64
import json
import logging
import os
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
        title = kwargs.get(ATTR_TITLE)
        targets = kwargs.get(ATTR_TARGET)
        data = kwargs.get(ATTR_DATA) or {}

        # Normalize targets / room
        target_list = None
        if isinstance(targets, str):
            target_list = [targets]
        elif isinstance(targets, list):
            target_list = targets

        room_id = data.get("room") or (target_list[0] if target_list else "homeassistant_bot")

        # Build payload with all redundant key aliases (room, sender, text, message, body) for 100% app & PocketBase compatibility
        payload = {
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
            "timestamp": asyncio.get_event_loop().time(),
        }

        # Handle Photo/Image attachments (URL, local file path, or base64)
        image_path_or_url = (
            data.get(ATTR_IMAGE)
            or data.get(ATTR_PHOTO)
            or data.get("path")
            or data.get("file_path")
            or data.get("file")
        )
        video_path_or_url = data.get(ATTR_VIDEO)
        camera_entity = data.get(ATTR_CAMERA)

        if camera_entity:
            # Automatic camera snapshot feature
            try:
                if hasattr(self.hass.components, "camera"):
                    image_result = await self.hass.components.camera.async_get_image(camera_entity)
                    if image_result and image_result.content:
                        b64_img = base64.b64encode(image_result.content).decode("utf-8")
                        payload["attachment"] = {
                            "type": "image",
                            "mime_type": image_result.content_type or "image/jpeg",
                            "data_base64": b64_img,
                            "source": f"camera:{camera_entity}",
                        }
                        payload["image"] = payload["attachment"]
            except Exception as err:
                _LOGGER.error("Failed to capture snapshot from camera %s: %s", camera_entity, err)

        elif image_path_or_url and isinstance(image_path_or_url, str) and not os.path.exists(image_path_or_url):
            if image_path_or_url.startswith(("http://", "https://")):
                payload["attachment"] = {
                    "type": "image",
                    "url": image_path_or_url,
                }
                payload["image"] = payload["attachment"]

        elif video_path_or_url:
            if video_path_or_url.startswith(("http://", "https://")):
                payload["attachment"] = {
                    "type": "video",
                    "url": video_path_or_url,
                }
                payload["video"] = payload["attachment"]
            elif os.path.exists(video_path_or_url):
                try:
                    with open(video_path_or_url, "rb") as vid_file:
                        b64_vid = base64.b64encode(vid_file.read()).decode("utf-8")
                        payload["attachment"] = {
                            "type": "video",
                            "mime_type": "video/mp4",
                            "data_base64": b64_vid,
                            "filename": os.path.basename(video_path_or_url),
                        }
                        payload["video"] = payload["attachment"]
                except Exception as err:
                    _LOGGER.error("Failed to read video file %s: %s", video_path_or_url, err)

        if "actions" in data:
            payload["actions"] = data["actions"]

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

        # 3. Post REST payload directly to PocketBase / REST push gateway endpoint
        session = async_get_clientsession(self.hass)
        raw_base_url = (self.public_url or "").strip()

        # If public_url is the HA server domain (beeserver.org), map to PocketBase domain pocket.nextbee.org
        if "beeserver.org" in raw_base_url and "pocket" not in raw_base_url:
            base_url = "https://pocket.nextbee.org"
        else:
            base_url = raw_base_url or "https://pocket.nextbee.org"

        if "records" in base_url:
            target_url = base_url
        elif base_url.startswith(("http://", "https://")):
            target_url = f"{base_url.rstrip('/')}/api/collections/messages/records"
        else:
            target_url = "https://pocket.nextbee.org/api/collections/messages/records"

        candidate_urls = [
            target_url,
            "https://pocket.nextbee.org/api/collections/messages/records",
            "http://192.168.178.74:8090/api/collections/messages/records",
        ]
        # Remove duplicates preserving order
        candidate_urls = list(dict.fromkeys(candidate_urls))

        headers = {}
        if self.secret_token:
            headers["Authorization"] = f"Bearer {self.secret_token}"

        success = False

        # If local image file exists, post via FormData multipart file upload
        if image_path_or_url and isinstance(image_path_or_url, str) and os.path.exists(image_path_or_url):
            text_val = f"{title}\n{message}" if title else message
            _LOGGER.warning("ADLOS_REST: Sending photo to candidate URLs (room=%s, file=%s): %s", room_id, image_path_or_url, text_val)

            for url in candidate_urls:
                try:
                    form_data = aiohttp.FormData()
                    form_data.add_field("text", text_val)
                    form_data.add_field("sender", "Home Assistant")
                    form_data.add_field("room", room_id)
                    form_data.add_field("type", "image")

                    with open(image_path_or_url, "rb") as f:
                        form_data.add_field("file", f, filename=os.path.basename(image_path_or_url))

                        async with session.post(url, data=form_data, headers=headers, timeout=15) as resp:
                            resp_body = await resp.text()
                            if resp.status in (200, 201, 204):
                                _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", resp.status, url, resp_body)
                                success = True
                                break
                            else:
                                _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", resp.status, url, resp_body)
                except Exception as err:
                    _LOGGER.error("ADLOS_REST EXCEPTION posting photo to %s: %s", url, err)
        else:
            headers["Content-Type"] = "application/json"
            _LOGGER.warning("ADLOS_REST: Sending message to candidate URLs (room=%s): %s", room_id, message)

            for url in candidate_urls:
                try:
                    async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
                        resp_body = await resp.text()
                        if resp.status in (200, 201, 204):
                            _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", resp.status, url, resp_body)
                            success = True
                            break
                        else:
                            _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", resp.status, url, resp_body)
                except Exception as err:
                    _LOGGER.error("ADLOS_REST EXCEPTION posting to %s: %s", url, err)

        if not success:
            _LOGGER.error("ADLOS_REST: Failed to post message to all candidate URLs: %s", candidate_urls)
