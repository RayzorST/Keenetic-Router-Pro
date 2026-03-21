"""Select entities for Keenetic Router Pro (client connection policy)."""
from __future__ import annotations
import logging
from typing import Any
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .api import KeeneticClient
from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR, CONF_TRACKED_CLIENTS
from .coordinator import KeeneticCoordinator
from .entity import ClientEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Keenetic Router Pro select entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KeeneticCoordinator = data[DATA_COORDINATOR]
    client: KeeneticClient = data[DATA_CLIENT]
    entities: list[SelectEntity] = []

    # Policy listesini al
    policies = await client.async_get_policies()

    # Tracked client'lar için policy select entity'leri
    tracked_clients = entry.data.get(CONF_TRACKED_CLIENTS, [])

    for client_info in tracked_clients:
        if not isinstance(client_info, dict):
            continue
        
        mac = str(client_info.get("mac") or "").lower()
        if not mac:
            continue
        
        name = client_info.get("name") or mac.upper()
        initial_ip = client_info.get("ip")
        
        entities.append(
            KeeneticClientPolicySelect(
                coordinator=coordinator,
                entry=entry,
                api_client=client,
                mac=mac,
                label=name,
                initial_ip=initial_ip,
                policies=policies,
            )
        )

    if entities:
        async_add_entities(entities)


class KeeneticClientPolicySelect(ClientEntity, SelectEntity):
    """Select entity for client connection policy, attached to client device."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-account"

    def __init__(
        self,
        coordinator: KeeneticCoordinator,
        entry: ConfigEntry,
        api_client: KeeneticClient,
        mac: str,
        label: str,
        initial_ip: str | None,
        policies: dict[str, str],
    ) -> None:
        """Initialize the policy select entity."""
        ClientEntity.__init__(
            self,
            coordinator=coordinator,
            entry_id=entry.entry_id,
            title=entry.title,
            mac=mac,
            label=label,
            initial_ip=initial_ip,
        )
        self._api_client = api_client
        self._policies = policies
        
        # Build mapping between policy IDs and display names
        self._id_to_display: dict[str, str] = {}
        self._display_to_id: dict[str, str] = {}
        
        # Default policy (no specific policy)
        self._id_to_display["__default__"] = "Default"
        self._display_to_id["Default"] = "__default__"
        
        # Deny policy (blocked)
        self._id_to_display["__deny__"] = "Deny (Blocked)"
        self._display_to_id["Deny (Blocked)"] = "__deny__"
        
        # Custom policies from router
        for policy_id, description in policies.items():
            self._id_to_display[policy_id] = description
            self._display_to_id[description] = policy_id

    @property
    def unique_id(self) -> str:
        """Return unique ID for entity."""
        return f"{self._entry_id}_client_{self._mac}_policy"

    @property
    def name(self) -> str:
        """Return name of the entity."""
        return "Connection Policy"

    @property
    def options(self) -> list[str]:
        """Return list of available options."""
        policy_names = sorted(self._policies.values())
        return ["Default"] + policy_names + ["Deny (Blocked)"]

    @property
    def current_option(self) -> str | None:
        """Return current selected policy."""
        host_policies = self.coordinator.data.get("host_policies", {})
        
        host_info = host_policies.get(self._mac, {})
        access = host_info.get("access")
        policy_id = host_info.get("policy")
        
        if access == "deny":
            return "Deny (Blocked)"
        
        if policy_id and policy_id in self._id_to_display:
            return self._id_to_display[policy_id]
        
        return "Default"

    async def async_select_option(self, option: str) -> None:
        """Change the selected policy."""
        if option == "Default":
            await self._api_client.async_set_client_policy(self._mac, "default")
        elif option == "Deny (Blocked)":
            await self._api_client.async_set_client_policy(self._mac, "deny")
        else:
            policy_id = self._display_to_id.get(option)
            if policy_id and policy_id not in ("__default__", "__deny__"):
                await self._api_client.async_set_client_policy(self._mac, policy_id)
        
        # Refresh coordinator to update state
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        host_policies = self.coordinator.data.get("host_policies", {})
        host_info = host_policies.get(self._mac, {})
        
        # Get current policy details
        current_policy_id = host_info.get("policy")
        current_policy_desc = None
        if current_policy_id and current_policy_id in self._id_to_display:
            current_policy_desc = self._id_to_display[current_policy_id]
        
        return {
            "mac": self._mac.upper(),
            "client_name": self.hostname or self._label,
            "policy_id": current_policy_id,
            "policy_description": current_policy_desc,
            "access": host_info.get("access"),
            "available_policies": list(self._policies.values()),
            "is_registered": host_info.get("registered", False),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if client is known to the router
        return self._client is not None