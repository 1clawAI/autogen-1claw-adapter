# Integration Verification

This document records the end-to-end integration test results for `autogen-1claw-adapter` — proving the adapter actually wraps as a real AutoGen `FunctionTool` and routes a live HTTP call through the vault.

## Test environment

- Python 3.14.2 (CPython)
- `autogen-agentchat` 0.7.5
- `autogen-core` (transitive)
- `requests` 2.34.2
- `pytest` 9.0.3

## What gets exercised

**Shape compatibility** — the adapter returns a real `autogen_core.tools.FunctionTool` (subclass of `BaseTool`) that `AssistantAgent` accepts directly via `tools=[...]`.

**Typed schema** — when a Pydantic `args_model` is provided, the LLM-facing schema reflects the model's fields (`latitude`, `longitude`, `current_weather`, etc.), so tool-calling LLMs get proper typed arguments. A fallback path emits a generic `kwargs: dict` schema when no model is provided.

**Real upstream call** — the integration test routes through:

```
autogen FunctionTool.run_json(args, CancellationToken)
    → typed args validation (Pydantic args_model)
    → autogen_1claw VaultBackedTool.__call__(...)
    → MockVault.submit_intent(...)
    → policy check (endpoint allowlist, per-call cap, daily cap, tool allowlist, allowed_agents)
    → http_caller(endpoint, args, credential)
    → requests.get("https://api.open-meteo.com/v1/forecast", ...)
    → JSON response back to the agent
```

The API used is [Open-Meteo](https://open-meteo.com/) — free, no auth, suitable for CI. The vault holds the credential handle; the agent never reads it.

**Denial paths** — three denial modes verified through the live AutoGen call path:

1. **Endpoint allowlist violation** — `IntentDeniedError` surfaces through `FunctionTool.run_json` for endpoints outside the policy.
2. **allowed_agents violation** — a `VaultBackedTool` scoped to a different agent (`with_agent("ResearchAgent")`) is denied even though the underlying credential exists.
3. **Audit logging** — every call, allowed or denied, is recorded in the vault's audit log.

## Test results

```
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/kevinjones/autogen-1claw-adapter
configfile: pyproject.toml
collected 17 items

tests/test_autogen_integration.py::test_adapter_converts_to_autogen_function_tool PASSED
tests/test_autogen_integration.py::test_schema_reflects_args_model_when_provided PASSED
tests/test_autogen_integration.py::test_schema_fallback_is_generic_kwargs_when_no_model PASSED
tests/test_autogen_integration.py::test_real_http_call_through_vault_returns_weather_data PASSED
tests/test_autogen_integration.py::test_vault_denies_endpoint_outside_allowlist_via_autogen_path PASSED
tests/test_autogen_integration.py::test_agent_id_denial_via_autogen_path PASSED
tests/test_autogen_integration.py::test_audit_log_records_real_http_call_via_autogen PASSED
tests/test_basic.py::test_happy_path_returns_response_and_records_audit PASSED
tests/test_basic.py::test_credential_never_exposed PASSED
tests/test_basic.py::test_agent_not_in_allowed_agents_denied PASSED
tests/test_basic.py::test_with_agent_returns_new_tool_with_different_id PASSED
tests/test_basic.py::test_endpoint_outside_allowlist_denied PASSED
tests/test_basic.py::test_per_call_cap_denial PASSED
tests/test_basic.py::test_daily_cap_denial_after_repeated_calls PASSED
tests/test_basic.py::test_tool_allowlist_denial PASSED
tests/test_basic.py::test_middleware_invokes_tool_fn_after_approval PASSED
tests/test_basic.py::test_middleware_denies_without_calling_tool_fn PASSED

======================== 17 passed in 1.59s ==========================
```

## Implementation note: schema inference

AutoGen's `FunctionTool` infers the LLM-facing JSON schema from the wrapped callable's signature annotations. A `def __call__(self, **kwargs)` shape generates a schema with a single nested `kwargs` field — the LLM has to know to pack everything inside it.

The fix in `src/autogen_1claw/integrations/autogen_compat.py`: when a Pydantic `args_model` is provided, synthesize a wrapper function with explicit annotations matching the model's fields. `FunctionTool` then emits a proper per-field schema that tool-calling LLMs handle cleanly.

This pattern is recommended for production use — provide an `args_model` so the LLM gets a typed contract.

## How to re-run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest autogen-agentchat requests
pytest tests/ -v
```

## Open follow-ups (Tier 2 — needs LLM API key)

The current test does not yet exercise:

- A live `AssistantAgent` with a real `ChatCompletionClient` (Anthropic / OpenAI) using the vault-backed tool through a multi-turn conversation
- Verification that the credential string never appears in any message in the conversation history
- A prompt-injection attempt asking the agent to leak its credential

These tests need an LLM key in the vault as the credential. Tracked separately; not yet run.
