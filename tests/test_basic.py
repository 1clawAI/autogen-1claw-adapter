"""Sanity tests for MockVault + VaultBackedTool + VaultMiddleware."""

import pytest

from autogen_1claw import IntentDeniedError, MockVault, VaultBackedTool, VaultMiddleware


def _vault(http_caller=None):
    return MockVault(
        policies={
            "test-cred": {
                "endpoint_allowlist": ["https://api.example/*"],
                "per_call_usd_cap": 0.10,
                "daily_usd_cap": 0.50,
                "allowed_tools": ["allowed_tool"],
                "allowed_agents": ["TrustedAgent"],
            },
        },
        credentials={"test-cred": "secret-stays-here"},
        http_caller=http_caller or (lambda e, a, c: {"ok": True, "endpoint": e, "args": a}),
    )


def _tool(vault, **overrides):
    defaults = dict(
        name="allowed_tool",
        description="test",
        vault=vault,
        credential_handle="test-cred",
        endpoint="https://api.example/v1/thing",
        estimated_usd_per_call=0.01,
        agent_id="TrustedAgent",
    )
    defaults.update(overrides)
    return VaultBackedTool(**defaults)


def test_happy_path_returns_response_and_records_audit():
    vault = _vault()
    tool = _tool(vault)
    resp = tool(query="hello")
    assert resp["ok"] is True
    assert resp["args"] == {"query": "hello"}
    assert len(vault.audit_log()) == 1
    intent, result, audit_id = vault.audit_log()[0]
    assert result.ok is True
    assert audit_id


def test_credential_never_exposed():
    vault = _vault()
    tool = _tool(vault)
    resp = tool(query="x")
    assert "secret-stays-here" not in str(resp)


def test_agent_not_in_allowed_agents_denied():
    vault = _vault()
    tool = _tool(vault, agent_id="UntrustedAgent")
    with pytest.raises(IntentDeniedError) as exc:
        tool(query="hello")
    assert "allowed_agents" in str(exc.value)


def test_with_agent_returns_new_tool_with_different_id():
    vault = _vault()
    a = _tool(vault)
    b = a.with_agent("OtherAgent")
    assert a._agent_id == "TrustedAgent"
    assert b._agent_id == "OtherAgent"
    # Original allowed, the swapped one denied
    a(query="hello")
    with pytest.raises(IntentDeniedError):
        b(query="hello")


def test_endpoint_outside_allowlist_denied():
    vault = _vault()
    tool = _tool(vault, endpoint="https://api.evil.example/exfil")
    with pytest.raises(IntentDeniedError) as exc:
        tool(query="hello")
    assert "allowlist" in str(exc.value)


def test_per_call_cap_denial():
    vault = _vault()
    tool = _tool(vault, estimated_usd_per_call=0.20)
    with pytest.raises(IntentDeniedError) as exc:
        tool(query="hello")
    assert "per_call_usd_cap" in str(exc.value)


def test_daily_cap_denial_after_repeated_calls():
    vault = _vault()
    tool = _tool(vault, estimated_usd_per_call=0.20)
    vault._policies["test-cred"]["per_call_usd_cap"] = 1.00
    tool(query="1")
    tool(query="2")
    with pytest.raises(IntentDeniedError) as exc:
        tool(query="3")
    assert "daily_usd_cap" in str(exc.value)


def test_tool_allowlist_denial():
    vault = _vault()
    tool = _tool(vault, name="not_allowed_tool")
    with pytest.raises(IntentDeniedError) as exc:
        tool(query="hello")
    assert "not in allowed_tools" in str(exc.value)


def test_middleware_invokes_tool_fn_after_approval():
    vault = _vault()
    mw = VaultMiddleware(vault=vault, default_agent_id="TrustedAgent")
    called_with = {}

    def downstream(**kwargs):
        called_with.update(kwargs)
        return {"downstream": True, **kwargs}

    out = mw.invoke(
        tool_fn=downstream,
        tool_name="allowed_tool",
        credential_handle="test-cred",
        endpoint="https://api.example/v1/thing",
        args={"x": 1},
        estimated_usd=0.01,
    )
    assert out == {"downstream": True, "x": 1}
    assert called_with == {"x": 1}


def test_middleware_denies_without_calling_tool_fn():
    vault = _vault()
    mw = VaultMiddleware(vault=vault, default_agent_id="UntrustedAgent")
    called = {"n": 0}

    def downstream(**kwargs):
        called["n"] += 1
        return "called"

    with pytest.raises(IntentDeniedError):
        mw.invoke(
            tool_fn=downstream,
            tool_name="allowed_tool",
            credential_handle="test-cred",
            endpoint="https://api.example/v1/thing",
            args={"x": 1},
            estimated_usd=0.01,
        )
    assert called["n"] == 0  # never invoked
