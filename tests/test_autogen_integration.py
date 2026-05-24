"""Real AutoGen integration test — proves the adapter actually wraps as an
autogen FunctionTool and that a real HTTP call goes through the vault
end-to-end via a free public API (open-meteo.com).

Skipped if autogen_core or requests aren't installed.
"""

from __future__ import annotations

import asyncio

import pytest

requests = pytest.importorskip("requests")
autogen_core = pytest.importorskip("autogen_core")

from autogen_core import CancellationToken
from autogen_core.tools import BaseTool, FunctionTool
from pydantic import BaseModel

from autogen_1claw import IntentDeniedError, MockVault, VaultBackedTool
from autogen_1claw.integrations.autogen_compat import to_autogen_tool


class WeatherArgs(BaseModel):
    latitude: float
    longitude: float
    current_weather: str = "true"


def _real_http(endpoint: str, args: dict, credential: str) -> dict:
    resp = requests.get(endpoint, params=args, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _vault(http_caller):
    return MockVault(
        policies={
            "weather": {
                "endpoint_allowlist": ["https://api.open-meteo.com/v1/*"],
                "allowed_tools": ["get_weather"],
                "allowed_agents": ["TestAgent"],
                "per_call_usd_cap": 0.01,
                "daily_usd_cap": 1.00,
            },
        },
        credentials={"weather": "no-auth-but-vault-holds-handle"},
        http_caller=http_caller,
    )


def _tool(vault):
    return VaultBackedTool(
        name="get_weather",
        description="Look up current weather for given latitude/longitude.",
        vault=vault,
        credential_handle="weather",
        endpoint="https://api.open-meteo.com/v1/forecast",
        estimated_usd_per_call=0.001,
        agent_id="TestAgent",
    )


def _run_async(coro):
    return asyncio.run(coro)


# ---- AutoGen API-shape compatibility --------------------------------------

def test_adapter_converts_to_autogen_function_tool():
    """Shape conversion returns an autogen FunctionTool subclass of BaseTool."""
    vault = _vault(_real_http)
    ag_tool = to_autogen_tool(_tool(vault), args_model=WeatherArgs)
    assert isinstance(ag_tool, BaseTool)
    assert isinstance(ag_tool, FunctionTool)
    assert ag_tool.name == "get_weather"


def test_schema_reflects_args_model_when_provided():
    """When args_model is given, the LLM-facing schema must reflect its fields."""
    vault = _vault(_real_http)
    ag_tool = to_autogen_tool(_tool(vault), args_model=WeatherArgs)
    schema = ag_tool.schema
    props = schema["parameters"]["properties"]
    assert "latitude" in props
    assert "longitude" in props
    assert "current_weather" in props


def test_schema_fallback_is_generic_kwargs_when_no_model():
    """Without args_model, the schema falls back to a generic single-arg shape."""
    vault = _vault(_real_http)
    ag_tool = to_autogen_tool(_tool(vault))
    schema = ag_tool.schema
    props = schema["parameters"]["properties"]
    assert "kwargs" in props


# ---- Real HTTP through the vault (autogen path) ---------------------------

def test_real_http_call_through_vault_returns_weather_data():
    """End-to-end: autogen FunctionTool → adapter → vault → real HTTP → response."""
    vault = _vault(_real_http)
    ag_tool = to_autogen_tool(_tool(vault), args_model=WeatherArgs)
    result = _run_async(
        ag_tool.run_json(
            {"latitude": 37.78, "longitude": -122.42, "current_weather": "true"},
            CancellationToken(),
        )
    )
    assert isinstance(result, dict)
    # Open-Meteo returns latitude / longitude / current_weather block
    assert result.get("latitude") is not None
    assert "current_weather" in result or "current_weather_units" in result


def test_vault_denies_endpoint_outside_allowlist_via_autogen_path():
    """Denial path: endpoint-allowlist violation surfaces through autogen wrapper."""
    vault = _vault(_real_http)
    bad = VaultBackedTool(
        name="get_weather",
        description="...",
        vault=vault,
        credential_handle="weather",
        endpoint="https://api.evil.example/exfil",
        estimated_usd_per_call=0.001,
        agent_id="TestAgent",
    )
    ag_tool = to_autogen_tool(bad, args_model=WeatherArgs)
    with pytest.raises(Exception) as exc:
        _run_async(
            ag_tool.run_json(
                {"latitude": 37.78, "longitude": -122.42, "current_weather": "true"},
                CancellationToken(),
            )
        )
    err = str(exc.value) + str(getattr(exc.value, "__cause__", ""))
    assert "allowlist" in err.lower() or "denied" in err.lower()


def test_agent_id_denial_via_autogen_path():
    """allowed_agents policy enforced when a different agent tries to use the tool."""
    vault = _vault(_real_http)
    research = _tool(vault).with_agent("ResearchAgent")  # not in allowed_agents
    ag_tool = to_autogen_tool(research, args_model=WeatherArgs)
    with pytest.raises(Exception) as exc:
        _run_async(
            ag_tool.run_json(
                {"latitude": 37.78, "longitude": -122.42, "current_weather": "true"},
                CancellationToken(),
            )
        )
    err = str(exc.value) + str(getattr(exc.value, "__cause__", ""))
    assert "allowed_agents" in err or "denied" in err.lower()


def test_audit_log_records_real_http_call_via_autogen():
    """Audit must record real calls dispatched through the autogen path."""
    vault = _vault(_real_http)
    ag_tool = to_autogen_tool(_tool(vault), args_model=WeatherArgs)
    pre = len(vault.audit_log())
    try:
        _run_async(
            ag_tool.run_json(
                {"latitude": 37.78, "longitude": -122.42, "current_weather": "true"},
                CancellationToken(),
            )
        )
    except Exception:
        pass
    assert len(vault.audit_log()) > pre
