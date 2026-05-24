"""VaultMiddleware — agent-level enforcement on EVERY tool call from an agent.

This is the second usage pattern (vs. per-tool `VaultBackedTool`): a single
middleware that intercepts every tool invocation an agent makes and routes
it through the vault. Useful when an agent has many tools and you want one
enforcement point instead of wrapping each tool individually.

Once microsoft/autogen#7613 (the governance middleware extension) lands
upstream, this class will implement that interface natively. Today it's a
thin wrapper that the caller invokes explicitly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .intent import Intent, IntentDeniedError
from .vault import Vault


class VaultMiddleware:
    """Wraps tool calls in a vault-checked intent.

    Usage:
        mw = VaultMiddleware(vault=my_vault, default_agent_id="BillingAgent")
        result = mw.invoke(
            tool_fn=my_callable,
            tool_name="charge_card",
            credential_handle="stripe",
            endpoint="https://api.stripe.com/v1/charges",
            args={"amount": 499},
            estimated_usd=4.99,
        )
    """

    def __init__(
        self,
        vault: Vault,
        default_agent_id: Optional[str] = None,
    ):
        self._vault = vault
        self._default_agent_id = default_agent_id

    def invoke(
        self,
        tool_fn: Optional[Callable[..., Any]],
        tool_name: str,
        credential_handle: str,
        endpoint: str,
        args: dict[str, Any],
        estimated_usd: float = 0.0,
        agent_id: Optional[str] = None,
    ) -> Any:
        """Build an Intent, check policy, then either call tool_fn (if the
        vault doesn't already perform the upstream call) or return the vault's
        response directly.

        If tool_fn is None, the vault's MockVault-style http_caller is the
        only path that runs. If tool_fn is provided, it runs AFTER the vault
        approves the intent — the agent still doesn't see the credential, but
        the caller controls the upstream request shape.
        """
        intent = Intent(
            tool_name=tool_name,
            credential_handle=credential_handle,
            endpoint=endpoint,
            args=args,
            estimated_usd=estimated_usd,
            agent_id=agent_id or self._default_agent_id,
        )
        result = self._vault.submit_intent(intent)
        if not result.ok:
            raise IntentDeniedError(result.denial_reason or "policy denied", intent)
        if tool_fn is not None:
            # Vault approved; caller's tool runs without holding the raw credential
            # (the credential stayed inside the vault and was only used there).
            return tool_fn(**args)
        return result.response
