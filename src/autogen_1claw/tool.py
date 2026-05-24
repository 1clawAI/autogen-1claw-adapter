"""VaultBackedTool — callable shape compatible with AutoGen's tool registration."""

from __future__ import annotations

from typing import Any, Optional

from .intent import Intent, IntentDeniedError
from .vault import Vault


class VaultBackedTool:
    """A tool that resolves credentials via a Vault instead of holding them.

    Designed to drop into `ConversableAgent.register_for_llm(...)` and
    `register_for_execution(...)` patterns. The instance is callable, so it
    can be registered directly or via the `as_callable()` shorthand.

    The class does NOT import autogen — this keeps the package usable as a
    pure dependency-free reference. Wire to AutoGen at the call site.
    """

    def __init__(
        self,
        name: str,
        description: str,
        vault: Vault,
        credential_handle: str,
        endpoint: str,
        estimated_usd_per_call: float = 0.0,
        agent_id: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        self._vault = vault
        self._credential_handle = credential_handle
        self._endpoint = endpoint
        self._estimated_usd_per_call = estimated_usd_per_call
        self._agent_id = agent_id

    def __call__(self, **kwargs: Any) -> Any:
        """Tool invocation. AutoGen calls this with the tool args."""
        intent = Intent(
            tool_name=self.name,
            credential_handle=self._credential_handle,
            endpoint=self._endpoint,
            args=kwargs,
            estimated_usd=self._estimated_usd_per_call,
            agent_id=self._agent_id,
        )
        result = self._vault.submit_intent(intent)
        if not result.ok:
            raise IntentDeniedError(result.denial_reason or "policy denied", intent)
        return result.response

    def with_agent(self, agent_id: str) -> "VaultBackedTool":
        """Return a new tool instance scoped to a specific agent_id.

        Useful in multi-agent setups where the same tool is registered for
        multiple ConversableAgents and the vault should distinguish them.
        """
        return VaultBackedTool(
            name=self.name,
            description=self.description,
            vault=self._vault,
            credential_handle=self._credential_handle,
            endpoint=self._endpoint,
            estimated_usd_per_call=self._estimated_usd_per_call,
            agent_id=agent_id,
        )

    def __repr__(self) -> str:
        return (
            f"VaultBackedTool(name={self.name!r}, "
            f"handle={self._credential_handle!r}, agent={self._agent_id!r})"
        )
