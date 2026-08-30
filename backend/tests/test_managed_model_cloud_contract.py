from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPOSITORY_ROOT / "supabase" / "migrations" / "20260726060000_create_model_access_billing.sql"
)
SUPABASE_CONFIG = REPOSITORY_ROOT / "supabase" / "config.toml"
MODEL_GATEWAY = REPOSITORY_ROOT / "supabase" / "functions" / "model-gateway" / "index.ts"
BILLING_CHECKOUT = REPOSITORY_ROOT / "supabase" / "functions" / "billing-checkout" / "index.ts"
AGENT_CORE_PLANNING = (
    REPOSITORY_ROOT / "frontend" / "src" / "features" / "autonomy" / "agentCorePlanning.ts"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_three_plans_share_one_capability_set_and_only_quota_price_vary() -> None:
    migration = _text(MIGRATION)

    assert "check (capability_set = 'core-v1')" in migration
    assert "check (plan_id in ('free', 'plus', 'pro'))" in migration
    assert "('free', 'Free', 1, 0, 300000, 'core-v1', 1)" in migration
    assert "('plus', 'Plus', 2, 3900, 3000000, 'core-v1', 1)" in migration
    assert "('pro', 'Pro', 3, 12900, 15000000, 'core-v1', 1)" in migration
    assert "payment_method in ('alipay', 'wechat', 'card')" in migration
    assert "business" not in migration.lower()


def test_cloud_tables_are_rls_protected_and_mutating_rpcs_are_service_only() -> None:
    migration = _text(MIGRATION)
    protected_tables = (
        "model_subscription_plans",
        "account_entitlements",
        "model_usage_periods",
        "model_gateway_grants",
        "model_usage_requests",
        "payment_orders",
        "payment_webhook_events",
    )
    service_functions = (
        "model_access_ensure_period",
        "model_access_snapshot",
        "model_gateway_issue_grant",
        "model_usage_reserve",
        "model_usage_settle",
        "model_usage_fail",
        "billing_create_order",
        "billing_mark_order_paid",
    )

    for table in protected_tables:
        assert f"alter table public.{table} enable row level security;" in migration
    for function in service_functions:
        assert f"revoke all on function public.{function}" in migration
        assert f"grant execute on function public.{function}" in migration
    assert migration.count("security definer") == len(service_functions)
    assert migration.count("set search_path = ''") == len(service_functions)
    assert "to service_role;" in migration


def test_gateway_uses_hashed_scoped_grants_and_atomic_reservations() -> None:
    migration = _text(MIGRATION)
    gateway = _text(MODEL_GATEWAY)

    assert "token_sha256 text not null unique" in migration
    assert "for update;" in migration
    assert "MODEL_QUOTA_EXHAUSTED" in migration
    assert "RESERVATION_EXPIRED" in migration
    assert "max_calls integer not null check (max_calls between 1 and 256)" in migration
    assert "grant_calls := 256;" in migration
    assert "grant: token" in gateway
    assert "Deno.env.get(`${prefix}_API_KEY`)" in gateway
    assert 'globalFallback("PLATFORM_LLM_API_KEY")' in gateway
    assert 'Deno.env.get("PLATFORM_LLM_MODEL_ALIAS")' in gateway
    assert "providerJson.model =" in gateway
    assert "delete providerJson.system_fingerprint" in gateway
    assert (
        "providerText"
        not in gateway.split("if (!providerResponse.ok)", maxsplit=1)[1]
        .split("let providerJson", maxsplit=1)[0]
        .split("throw new GatewayError", maxsplit=1)[0]
    )
    assert "platform_llm_api_key" not in migration.lower()


def test_agent_core_platform_requests_remain_inside_the_metered_gateway() -> None:
    gateway = _text(MODEL_GATEWAY)
    planning = _text(AGENT_CORE_PLANNING)

    assert "await issueManagedModelGrant(" in planning
    assert planning.count('"assistant",') >= 2
    assert "model_grant: grant.grant" in planning
    assert "gateway_base_url: modelGatewayBaseUrl(grant)" in planning
    assert planning.count("gateway_base_url: modelGatewayBaseUrl(grant)") >= 2
    assert 'adminClient().rpc(\n    "model_usage_reserve"' in gateway
    assert 'adminClient().rpc("model_usage_settle"' in gateway
    assert "p_input_tokens: usage.input_tokens" in gateway
    assert "p_output_tokens: usage.output_tokens" in gateway
    assert "p_total_tokens: usage.total_tokens" in gateway
    assert "p_usage_estimated: usage.estimated" in gateway


def test_non_jwt_edge_routes_implement_explicit_auth_and_payment_verification() -> None:
    config = _text(SUPABASE_CONFIG)
    gateway = _text(MODEL_GATEWAY)
    billing = _text(BILLING_CHECKOUT)

    for function_name in (
        "model-gateway",
        "assistant-orchestrator",
        "billing-checkout",
    ):
        assert f"[functions.{function_name}]\nverify_jwt = false" in config
    assert "adminClient().auth.getUser(token)" in gateway
    assert 'grant.startsWith("ddg_")' in gateway
    assert "adminClient().auth.getUser(bearerToken(request))" in billing
    assert "rsaVerify(" in billing
    assert "decryptWechatResource" in billing
    assert "WECHAT_PLATFORM_CERTIFICATE_SERIAL" in billing
    assert 'amount?.currency !== "CNY"' in billing
    assert "verifyStripeSignature(" in billing
    assert 'request.headers.get("Stripe-Signature")' in billing
    assert 'event.type !== "checkout.session.completed"' in billing
    assert 'session.currency !== "cny"' in billing
    assert "metadata?.plan_id !== order.plan_id" in billing
    assert 'path === "/webhooks/card"' in billing
    assert "verified_server_callback_only" in billing
    assert "billing_mark_order_paid" in billing
