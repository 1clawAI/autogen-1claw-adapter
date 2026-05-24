"""Intent submission types.

An Intent is the agent's structured request to *use* a credential. The vault
holds the real credential and decides whether the intent is allowed by the
operator's policy. The agent never reads the credential itself.

This shape is identical to the LangChain adapter (deliberate — one vault,
many framework adapters).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Intent:
    """A request to use a vault-held credential for a specific tool call."""

    tool_name: str
    credential_handle: str
    endpoint: str
    args: dict[str, Any] = field(default_factory=dict)
    estimated_usd: float = 0.0
    agent_id: Optional[str] = None  # AutoGen agent name or IATP-style ID


@dataclass(frozen=True)
class IntentResult:
    ok: bool
    response: Any = None
    audit_id: Optional[str] = None
    denial_reason: Optional[str] = None


class IntentDeniedError(RuntimeError):
    def __init__(self, reason: str, intent: Intent):
        self.reason = reason
        self.intent = intent
        super().__init__(f"intent denied: {reason} (tool={intent.tool_name}, agent={intent.agent_id})")
