"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    CONF_AWAY_DELAY,
    CONF_HEARTBEAT,
    CONF_PRESENCE_ENTITY,
    CONF_TOPIC_PREFIX,
    DEFAULT_AWAY_DELAY,
    DEFAULT_HEARTBEAT,
    DEFAULT_TOPIC_PREFIX,
    DOMAIN,
    MAX_HEARTBEAT,
    MIN_HEARTBEAT,
    PRESENCE_DOMAINS,
)

DEFAULT_NAME = "SR655 Fan Control"


def normalize_prefix(prefix: str) -> str | None:
    """Return the topic prefix without surrounding slashes, or None if unusable."""
    prefix = prefix.strip().strip("/")
    if not prefix or len(prefix) > 200 or any(c in prefix for c in "#+$\x00 ") or "//" in prefix:
        return None
    return prefix


def _options_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    presence = defaults.get(CONF_PRESENCE_ENTITY)
    return {
        vol.Required(
            CONF_PRESENCE_ENTITY, **({"default": presence} if presence else {})
        ): EntitySelector(EntitySelectorConfig(domain=PRESENCE_DOMAINS)),
        vol.Required(CONF_AWAY_DELAY, default=defaults.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)): NumberSelector(
            NumberSelectorConfig(min=0, max=1440, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_HEARTBEAT, default=defaults.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT)): NumberSelector(
            NumberSelectorConfig(
                min=MIN_HEARTBEAT, max=MAX_HEARTBEAT, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
            )
        ),
    }


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_PRESENCE_ENTITY: user_input[CONF_PRESENCE_ENTITY],
        CONF_AWAY_DELAY: int(user_input[CONF_AWAY_DELAY]),
        CONF_HEARTBEAT: int(user_input[CONF_HEARTBEAT]),
    }


class SR655ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self.hass.config_entries.async_entries("mqtt"):
            return self.async_abort(reason="mqtt_not_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            prefix = normalize_prefix(user_input[CONF_TOPIC_PREFIX])
            if prefix is None:
                errors[CONF_TOPIC_PREFIX] = "invalid_topic"
            else:
                await self.async_set_unique_id(prefix)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_TOPIC_PREFIX: prefix},
                    options=_clean_options(user_input),
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): TextSelector(),
                vol.Required(
                    CONF_TOPIC_PREFIX, default=defaults.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
                ): TextSelector(),
                **_options_schema(defaults),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SR655OptionsFlow:
        return SR655OptionsFlow()


class SR655OptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean_options(user_input))
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_options_schema(dict(self.config_entry.options)))
        )
