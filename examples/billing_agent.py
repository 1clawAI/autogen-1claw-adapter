"""End-to-end example: a vault-backed billing tool with agent-identity enforcement.

Simulates a multi-agent AutoGen workflow where a BillingAgent is allowed to
charge cards but a separate ResearchAgent is not — even though both might
have the tool registered.

Run with:
    python examples/billing_agent.py
"""

from autogen_1claw import IntentDeniedError, MockVault, VaultBackedTool


def fake_stripe(endpoint: str, args: dict, credential: str) -> dict:
    """Stub upstream caller. In production this lives inside the vault."""
    return {
        "endpoint": endpoint,
        "amount": args.get("amount"),
        "credential_prefix": credential[:8] + "…",  # never exposed to the agent
        "charge_id": "ch_test_" + str(abs(hash(str(args))))[:10],
    }


def main() -> None:
    vault = MockVault(
        policies={
            "stripe-charge": {
                "endpoint_allowlist": ["https://api.stripe.com/v1/charges*"],
                "per_call_usd_cap": 50.00,
                "daily_usd_cap": 500.00,
                "allowed_tools": ["create_charge"],
                "allowed_agents": ["BillingAgent"],
            },
        },
        credentials={
            "stripe-charge": "sk_live_real_credential_stays_here",
        },
        http_caller=fake_stripe,
    )

    # Same tool definition; differs only by which agent it's bound to.
    charge_for_billing = VaultBackedTool(
        name="create_charge",
        description="Charge a customer in USD cents.",
        vault=vault,
        credential_handle="stripe-charge",
        endpoint="https://api.stripe.com/v1/charges",
        estimated_usd_per_call=4.99,
        agent_id="BillingAgent",
    )
    charge_for_research = charge_for_billing.with_agent("ResearchAgent")

    # 1. BillingAgent: allowed.
    print("BillingAgent (allowed):")
    print(" ", charge_for_billing(amount=499, currency="usd"))

    # 2. ResearchAgent: same tool, different identity, DENIED.
    print("\nResearchAgent (denied by allowed_agents):")
    try:
        charge_for_research(amount=499, currency="usd")
    except IntentDeniedError as e:
        print(" ", e)

    # 3. BillingAgent attempting a too-large charge: per-call cap.
    print("\nBillingAgent over per-call cap:")
    big_charge = VaultBackedTool(
        name="create_charge",
        description="...",
        vault=vault,
        credential_handle="stripe-charge",
        endpoint="https://api.stripe.com/v1/charges",
        estimated_usd_per_call=100.00,  # > per_call_usd_cap
        agent_id="BillingAgent",
    )
    try:
        big_charge(amount=10000, currency="usd")
    except IntentDeniedError as e:
        print(" ", e)

    # 4. Audit log shows allowed + denied calls together.
    print(f"\naudit log entries: {len(vault.audit_log())}")
    for intent, result, audit_id in vault.audit_log():
        status = "OK " if result.ok else "DENY"
        print(f"  {audit_id}  {status}  agent={intent.agent_id}  tool={intent.tool_name}")


if __name__ == "__main__":
    main()
