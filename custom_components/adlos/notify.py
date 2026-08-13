"""Adlos notification service platform."""

import asyncio
import base64
import logging
import os
import aiohttp

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
    BaseNotificationService,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_CAMERA,
    ATTR_IMAGE,
    ATTR_PHOTO,
    ATTR_VIDEO,
    CONF_PUBLIC_URL,
    CONF_SECRET_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType = None,
) -> BaseNotificationService:
    """Get the Adlos notification service."""
    if discovery_info is None:
        # Service configured via notify platform in configuration.yaml or entry
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
        self.public_url = entry_data.get(CONF_PUBLIC_URL, "")
        self.webhook_id = entry_data.get(CONF_WEBHOOK_ID, "")
        self.secret_token = entry_data.get(CONF_SECRET_TOKEN, "")

    async def async_send_message(self, message: str = "", **kwargs) -> None:
        """Send a notification message to Adlos."""
        title = kwargs.get(ATTR_TITLE)
        targets = kwargs.get(ATTR_TARGET)
        data = kwargs.get(ATTR_DATA) or {}

        # Normalize targets
        target_list = None
        if isinstance(targets, str):
            target_list = [targets]
        elif isinstance(targets, list):
            target_list = targets

        # Build payload
        payload = {
            "title": title or "Home Assistant",
            "message": message,
            "targets": target_list,
            "token": self.secret_token,
            "webhook_id": self.webhook_id,
            "timestamp": asyncio.get_event_loop().time(),
        }

        # Handle Photo/Image attachments (URL, local file path, or base64)
        image_path_or_url = data.get(ATTR_IMAGE) or data.get(ATTR_PHOTO)
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
            except Exception as err:
                _LOGGER.error("Failed to capture snapshot from camera %s: %s", camera_entity, err)

        elif image_path_or_url:
            if image_path_or_url.startswith(("http://", "https://")):
                payload["attachment"] = {
                    "type": "image",
                    "url": image_path_or_url,
                }
            elif os.path.exists(image_path_or_url):
                try:
                    with open(image_path_or_url, "rb") as img_file:
                        b64_img = base64.b64encode(img_file.read()).decode("utf-8")
                        payload["attachment"] = {
                            "type": "image",
                            "mime_type": "image/jpeg",
                            "data_base64": b64_img,
                            "filename": os.path.basename(image_path_or_url),
                        }
                except Exception as err:
                    _LOGGER.error("Failed to read image file %s: %s", image_path_or_url, err)

        elif video_path_or_url:
            if video_path_or_url.startswith(("http://", "https://")):
                payload["attachment"] = {
                    "type": "video",
                    "url": video_path_or_url,
                }
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
                except Exception as err:
                    _LOGGER.error("Failed to read video file %s: %s", video_path_or_url, err)

        # Include custom actions/buttons if specified
        if "actions" in data:
            payload["actions"] = data["actions"]

        _LOGGER.info(
            "Adlos Notification queued for targets %s: %s (Attachment: %s)",
            target_list,
            message,
            "yes" if "attachment" in payload else "no",
        )

        # Fire HA event for local notification listeners or websockets
        self.hass.bus.async_fire("adlos_notification_sent", payload)

        # If a public webhook/push server URL is configured, POST payload to Adlos push gateway
        if self.public_url and self.public_url.startswith(("http://", "https://")):
            session = async_get_clientsession(self.hass)
            target_url = f"{self.public_url}/api/adlos/push"
            try:
                async with session.post(target_url, json=payload, timeout=10) as resp:
                    if resp.status not in (200, 201, 204):
                        _LOGGER.warning("Adlos push gateway returned status code %s", resp.status)
            except Exception as err:
                _LOGGER.debug("Adlos push gateway notice (non-fatal): %s", err)
