"""Adapt a VaultBackedTool to AutoGen's `FunctionTool` API.

Lazy-imports autogen_core so the core package stays usable without
autogen-core / autogen-agentchat installed.

Usage:

    from pydantic import BaseModel
    from autogen_1claw import VaultBackedTool
    from autogen_1claw.integrations.autogen_compat import to_autogen_tool

    class WeatherArgs(BaseModel):
        latitude: float
        longitude: float
        current_weather: str = "true"

    ag_tool = to_autogen_tool(my_vault_backed_tool, args_model=WeatherArgs)
    # ag_tool is an autogen_core.tools.FunctionTool ready for AssistantAgent
"""

from __future__ import annotations

from typing import Any, Optional, Type

from ..tool import VaultBackedTool


def to_autogen_tool(
    adapter_tool: VaultBackedTool,
    args_model: Optional[Type[Any]] = None,
) -> Any:
    """Wrap a VaultBackedTool as an autogen_core.tools.FunctionTool.

    Args:
        adapter_tool: the underlying VaultBackedTool.
        args_model: optional Pydantic BaseModel describing the tool's args.
            Strongly recommended for real agent use — AutoGen uses the
            schema for LLM tool-calling. If omitted, a flexible schema with
            a single `kwargs: dict` field is generated (still works, but
            most LLMs handle a typed schema better).

    Returns a FunctionTool the caller can pass directly to
    `AssistantAgent(tools=[...])`.
    """
    try:
        from autogen_core.tools import FunctionTool
        from pydantic import BaseModel, create_model
    except ImportError as e:
        raise ImportError(
            "autogen_core and pydantic are required for to_autogen_tool. "
            "Install with `pip install autogen-core` (or autogen-agentchat)."
        ) from e

    if args_model is None:
        # Generic fallback: tool takes a single `kwargs: dict` parameter.
        # Synthesize a function whose signature has it explicitly so
        # FunctionTool's introspection emits a sensible schema.
        def _invoke(kwargs: dict) -> Any:  # type: ignore[no-untyped-def]
            return adapter_tool(**kwargs)

        return FunctionTool(
            _invoke,
            name=adapter_tool.name,
            description=adapter_tool.description,
        )

    # Typed path: synthesize a function whose signature matches args_model.
    # FunctionTool then derives a proper LLM-facing schema from the annotations.
    field_names = list(args_model.model_fields.keys())

    def _invoke(**kwargs: Any) -> Any:
        # Validate via the user's model (raises ValidationError on bad input).
        validated = args_model(**kwargs).model_dump()
        return adapter_tool(**validated)

    # Build a wrapper with explicit annotations so FunctionTool sees the right schema.
    # We do this by exec-ing a small function definition string built from field types.
    annotations = {
        name: field.annotation for name, field in args_model.model_fields.items()
    }
    params = ", ".join(
        f"{name}: __annotations__[{name!r}]" for name in field_names
    )
    body = f"def __wrap__({params}):\n    return __invoke__(**locals())\n"
    ns: dict[str, Any] = {
        "__annotations__": annotations,
        "__invoke__": _invoke,
    }
    exec(body, ns)
    wrap = ns["__wrap__"]
    wrap.__name__ = adapter_tool.name
    wrap.__doc__ = adapter_tool.description

    return FunctionTool(
        wrap,
        name=adapter_tool.name,
        description=adapter_tool.description,
    )
