"""Vault-backed credential resolution + policy-checked tool calls for AutoGen agents."""

from .intent import Intent, IntentResult, IntentDeniedError
from .vault import Vault, MockVault
from .tool import VaultBackedTool
from .middleware import VaultMiddleware

__all__ = [
    "Intent",
    "IntentResult",
    "IntentDeniedError",
    "Vault",
    "MockVault",
    "VaultBackedTool",
    "VaultMiddleware",
]

__version__ = "0.1.0a0"
