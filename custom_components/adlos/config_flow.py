"""Config flow for Adlos Home Assistant integration."""

import logging
import secrets
import urllib.parse
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.network import get_url

from .const import (
    CONF_CHANNEL_NAME,
    CONF_PUBLIC_URL,
    CONF_SECRET_TOKEN,
    CONF_WEBHOOK_ID,
    DEFAULT_NAME,
    DOMAIN,
)
from .qr_generator import generate_qr_data_uri

_LOGGER = logging.getLogger(__name__)


class AdlosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Adlos."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._channel_name = DEFAULT_NAME
        self._public_url = ""
        self._webhook_id = ""
        self._secret_token = ""
        self._pairing_uri = ""

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            self._channel_name = user_input.get(CONF_CHANNEL_NAME, DEFAULT_NAME)
            self._public_url = user_input.get(CONF_PUBLIC_URL, "").rstrip("/")

            if not self._public_url:
                try:
                    self._public_url = get_url(self.hass, allow_internal=False, allow_external=True)
                except Exception:
                    self._public_url = get_url(self.hass)

            # Generate unique credentials for this HA installation
            self._webhook_id = f"adlos_{secrets.token_hex(12)}"
            self._secret_token = secrets.token_urlsafe(32)

            # Build pairing URI: adlos://connect?url=...&webhook_id=...&token=...&name=...
            params = {
                "url": self._public_url,
                "webhook_id": self._webhook_id,
                "token": self._secret_token,
                "name": self._channel_name,
            }
            self._pairing_uri = f"adlos://connect?{urllib.parse.urlencode(params)}"

            return await self.async_step_qr_code()

        # Try auto-detecting base URL for default UI value
        try:
            detected_url = get_url(self.hass, allow_internal=False, allow_external=True)
        except Exception:
            detected_url = ""

        schema = vol.Schema(
            {
                vol.Optional(CONF_CHANNEL_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_PUBLIC_URL, default=detected_url): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_qr_code(self, user_input=None):
        """Show QR Code for quick pairing with Adlos mobile app."""
        if user_input is not None:
            # Save configuration entry
            return self.async_create_entry(
                title=self._channel_name,
                data={
                    CONF_CHANNEL_NAME: self._channel_name,
                    CONF_PUBLIC_URL: self._public_url,
                    CONF_WEBHOOK_ID: self._webhook_id,
                    CONF_SECRET_TOKEN: self._secret_token,
                },
            )

        qr_data_uri = generate_qr_data_uri(self._pairing_uri)
        qr_img_html = f'<p align="center"><img src="{qr_data_uri}" width="260" height="260" style="border-radius:12px; background:#ffffff; padding:16px; box-shadow:0 4px 16px rgba(0,0,0,0.2);" /></p>'

        return self.async_show_form(
            step_id="qr_code",
            data_schema=vol.Schema({}),
            description_placeholders={
                "qr_code_img": qr_img_html,
                "pairing_uri": self._pairing_uri,
                "channel_name": self._channel_name,
                "public_url": self._public_url,
                "token": self._secret_token,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow handler."""
        return AdlosOptionsFlowHandler(config_entry)


class AdlosOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Adlos integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry_data = self.config_entry.data
        public_url = entry_data.get(CONF_PUBLIC_URL, "")
        webhook_id = entry_data.get(CONF_WEBHOOK_ID, "")
        token = entry_data.get(CONF_SECRET_TOKEN, "")
        name = entry_data.get(CONF_CHANNEL_NAME, DEFAULT_NAME)

        params = {
            "url": public_url,
            "webhook_id": webhook_id,
            "token": token,
            "name": name,
        }
        pairing_uri = f"adlos://connect?{urllib.parse.urlencode(params)}"
        qr_data_uri = generate_qr_data_uri(pairing_uri)
        qr_img_html = f'<p align="center"><img src="{qr_data_uri}" width="260" height="260" style="border-radius:12px; background:#ffffff; padding:16px; box-shadow:0 4px 16px rgba(0,0,0,0.2);" /></p>'

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={
                "qr_code_img": qr_img_html,
                "pairing_uri": pairing_uri,
                "webhook_id": webhook_id,
                "token": token,
            },
        )
