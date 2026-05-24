"""Vault protocol + MockVault reference implementation.

Same three-method interface as the langchain-1claw adapter, plus support for
an `allowed_agents` policy field (AutoGen-specific — pairs with agent identity
verification per microsoft/autogen#7440).
"""

from __future__ import annotations

import fnmatch
import uuid
from typing import Any, Protocol

from .intent import Intent, IntentDeniedError, IntentResult


class Vault(Protocol):
    """Minimal vault interface that autogen_1claw tools depend on."""

    def submit_intent(self, intent: Intent) -> IntentResult: ...

    def get_policy(self, credential_handle: str) -> dict[str, Any]: ...

    def record_audit(self, intent: Intent, result: IntentResult) -> str: ...


class MockVault:
    """Reference in-memory Vault.

    Policy fields supported:

      - endpoint_allowlist: list[str]   # fnmatch patterns
      - per_call_usd_cap:   float
      - daily_usd_cap:      float
      - allowed_tools:      list[str]
      - allowed_agents:     list[str]   # AutoGen-specific: gate by agent identity
    """

    def __init__(
        self,
        policies: dict[str, dict[str, Any]],
        credentials: dict[str, str],
        http_caller=None,
    ):
        self._policies = policies
        self._credentials = credentials
        self._spent_today: dict[str, float] = {}
        self._audit_log: list[tuple[Intent, IntentResult, str]] = []
        self._http_caller = http_caller or (lambda endpoint, args, cred: {
            "stub": True,
            "endpoint": endpoint,
            "args": args,
        })

    def submit_intent(self, intent: Intent) -> IntentResult:
        policy = self.get_policy(intent.credential_handle)

        # 1. Agent allowlist (AutoGen-specific)
        allowed_agents = policy.get("allowed_agents")
        if allowed_agents is not None and intent.agent_id not in allowed_agents:
            return self._deny(intent, f"agent_id '{intent.agent_id}' not in allowed_agents")

        # 2. Tool allowlist
        allowed_tools = policy.get("allowed_tools")
        if allowed_tools is not None and intent.tool_name not in allowed_tools:
            return self._deny(intent, f"tool '{intent.tool_name}' not in allowed_tools")

        # 3. Endpoint allowlist
        allowlist = policy.get("endpoint_allowlist") or []
        if allowlist and not any(fnmatch.fnmatch(intent.endpoint, pat) for pat in allowlist):
            return self._deny(intent, f"endpoint '{intent.endpoint}' not in allowlist")

        # 4. Per-call cap
        per_call = policy.get("per_call_usd_cap")
        if per_call is not None and intent.estimated_usd > per_call:
            return self._deny(
                intent,
                f"estimated_usd {intent.estimated_usd} exceeds per_call_usd_cap {per_call}",
            )

        # 5. Daily cap
        daily = policy.get("daily_usd_cap")
        spent = self._spent_today.get(intent.credential_handle, 0.0)
        if daily is not None and spent + intent.estimated_usd > daily:
            return self._deny(
                intent,
                f"would exceed daily_usd_cap {daily} (spent={spent}, this={intent.estimated_usd})",
            )

        credential = self._credentials.get(intent.credential_handle)
        if credential is None:
            return self._deny(intent, f"no credential for handle '{intent.credential_handle}'")

        response = self._http_caller(intent.endpoint, intent.args, credential)
        self._spent_today[intent.credential_handle] = spent + intent.estimated_usd

        result = IntentResult(ok=True, response=response)
        audit_id = self.record_audit(intent, result)
        return IntentResult(ok=True, response=response, audit_id=audit_id)

    def get_policy(self, credential_handle: str) -> dict[str, Any]:
        return self._policies.get(credential_handle, {})

    def record_audit(self, intent: Intent, result: IntentResult) -> str:
        audit_id = uuid.uuid4().hex[:12]
        self._audit_log.append((intent, result, audit_id))
        return audit_id

    def audit_log(self) -> list[tuple[Intent, IntentResult, str]]:
        return list(self._audit_log)

    def _deny(self, intent: Intent, reason: str) -> IntentResult:
        result = IntentResult(ok=False, denial_reason=reason)
        audit_id = self.record_audit(intent, result)
        return IntentResult(ok=False, denial_reason=reason, audit_id=audit_id)
