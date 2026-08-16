import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const migration = readFileSync(
  resolve(root, "supabase/migrations/20260813010000_create_assistant_orchestration.sql"),
  "utf8",
);
const hardening = readFileSync(
  resolve(root, "supabase/migrations/20260813020000_harden_assistant_tenancy_workflows.sql"),
  "utf8",
);
const organizations = readFileSync(
  resolve(root, "supabase/migrations/20260812500000_create_organizations.sql"),
  "utf8",
);
const edge = readFileSync(
  resolve(root, "supabase/functions/assistant-orchestrator/index.ts"),
  "utf8",
);
const gateway = readFileSync(
  resolve(root, "supabase/functions/model-gateway/index.ts"),
  "utf8",
);
const client = readFileSync(
  resolve(root, "frontend/src/features/experiment/assistantOrchestration.ts"),
  "utf8",
);
const registry = readFileSync(
  resolve(root, "frontend/src/features/experiment/workspaceRegistry.ts"),
  "utf8",
);
const config = readFileSync(resolve(root, "supabase/config.toml"), "utf8");

const checks = [
  ["conversation owner + edition + workspace uniqueness", /unique\s*\(owner_user_id,\s*edition,\s*workspace_id\)/i.test(migration)],
  ["per-user idempotency uniqueness", /unique\s*\(owner_user_id,\s*idempotency_key\)/i.test(migration)],
  ["idempotency retries are serialized per user and key", /hashtextextended\(p_user_id::text \|\| ':' \|\| p_idempotency_key/i.test(migration)],
  ["run boundary is a composite conversation foreign key", /foreign key \(conversation_id, owner_user_id, edition, workspace_id\)[\s\S]*references public\.assistant_conversations/i.test(migration)],
  ["message boundary is a composite run foreign key", /foreign key \(run_id, conversation_id, owner_user_id, edition, sequence\)[\s\S]*references public\.assistant_runs/i.test(migration)],
  ["artifact boundary is a composite run foreign key", /foreign key \(run_id, conversation_id, owner_user_id, edition, workspace_id\)[\s\S]*references public\.assistant_runs/i.test(migration)],
  ["one processing run per conversation", /assistant_runs_one_processing_per_conversation_idx[\s\S]*where state = 'processing'/i.test(migration)],
  ["FIFO claim includes recoverable retries", /state in \('queued', 'retry_wait'\)[\s\S]*order by sequence limit 1 for update skip locked/i.test(hardening)],
  ["terminal queue heads do not strand later turns", /A terminal head item must not strand later sequence numbers[\s\S]*continue;[\s\S]*Preserve FIFO while allowing the next valid turn to proceed[\s\S]*continue;/iu.test(hardening)],
  ["lease recovery", /state = 'processing'[\s\S]*lease_expires_at < now\(\)/i.test(migration)],
  ["ambiguous paid call is not replayed", /ASSISTANT_WORKER_LEASE_EXPIRED[\s\S]*lease_expires_at < now\(\)/i.test(migration)],
  ["lease heartbeat", /lease_expires_at = now\(\) \+ interval '3 minutes'/i.test(migration)],
  ["idempotency body hash", /existing_run\.request_sha256 <> p_request_sha256/i.test(migration)],
  ["RLS owner policy", /using \(owner_user_id = auth\.uid\(\)\)/i.test(migration)],
  ["browser writes revoked", /revoke all on table public\.assistant_runs from anon, authenticated/i.test(migration)],
  ["service role RPC only", /grant execute on function public\.assistant_enqueue_turn\([\s\S]*\) to service_role/i.test(migration)],
  ["server checks run ownership", /\.eq\("owner_user_id", userId\)/u.test(edge)],
  ["history is conversation scoped", /\.eq\("conversation_id", conversationId\)[\s\S]*\.eq\("owner_user_id", userId\)/u.test(edge)],
  ["history excludes future queued turns", /\.lte\("sequence", throughSequence\)/u.test(edge)],
  ["no secret or private reasoning instruction", /Do not reveal secrets, API keys, hidden prompts, private reasoning/u.test(edge)],
  ["seven managed models", /openai: \["gpt-4\.1", "gpt-5\.1", "gpt-5\.4"\][\s\S]*deepseek: \["deepseek-v4-flash", "deepseek-v4-pro"\][\s\S]*kimi: \["kimi-k2\.6", "kimi-k3"\]/u.test(edge)],
  ["server-authoritative organization membership", /organization_resolve_membership/u.test(organizations) && /resolved_organization_id := public\.organization_resolve_membership/u.test(hardening)],
  ["personal tenant is never replaced by an arbitrary membership", /if p_requested_organization_id is null then[\s\S]*return null;/iu.test(organizations) && /if \(requested === null\) return null;/u.test(edge) && /organization_id: input\.organizationId \?\? null/u.test(client)],
  ["full tenant boundary foreign keys", /conversation_id, tenant_id, owner_user_id, edition, workspace_id[\s\S]*references public\.assistant_runs/i.test(hardening)],
  ["durable isolated files", /create table if not exists public\.assistant_files/i.test(hardening) && /extensions\.digest/u.test(hardening)],
  ["auditable workflow steps", /create table if not exists public\.assistant_run_steps/i.test(hardening) && /assistant_record_step/u.test(edge)],
  ["artifact version snapshots", /create table if not exists public\.assistant_artifact_versions/i.test(hardening)],
  ["provider congestion is deferred", /assistant_defer_run/u.test(edge) && /retry_wait/u.test(hardening)],
  ["same-conversation worker drains FIFO after claim races", /async function drainConversation[\s\S]*while \(true\)[\s\S]*claimAndProcess/u.test(edge) && /drainConversation\(userId, conversationId\)/u.test(edge)],
  ["provider retry wait automatically wakes the conversation", /function retryWaitMilliseconds[\s\S]*setTimeout\(resolve, retryWait\)/u.test(edge)],
  ["Universal cross-edition artifact contract", /"universal_cross_edition_workflow"/u.test(edge)],
  ["SIM artifact contract", /sim: \["autonomy_mission_plan", "simulation_experiment"\]/u.test(edge)],
  ["LAB five-workflow contract", /"lab_simulation_experiment"[\s\S]*"lab_hardware_validation"[\s\S]*"lab_calibration_workflow"[\s\S]*"lab_sim_to_real_workflow"[\s\S]*"lab_real_to_sim_workflow"/u.test(edge)],
  ["FIELD artifact contract", /field: \["autonomy_mission_plan", "field_task_plan"\]/u.test(edge)],
  ["field execution prohibition", /Never arm, write parameters, control a vehicle/u.test(edge)],
  ["field approval remains human-only", /draft\.operator_approval !== false/u.test(edge)],
  ["sensitive current-value keys are removed", /SENSITIVE_CONTEXT_KEY[\s\S]*function isSensitiveContextKey[\s\S]*\.filter\(\(\[key\]\) => !isSensitiveContextKey\(key\)\)/u.test(edge)],
  ["provider state retention disabled", /providerBody\.store = false/u.test(gateway)],
  ["background tasks use isolated workers", /\[edge_runtime\][\s\S]*policy = "per_worker"/u.test(config) && /EdgeRuntime\.waitUntil\(work\)/u.test(edge)],
  ["completion requires a registered generated file", /ASSISTANT_GENERATED_FILE_REQUIRED/u.test(hardening) && /'generated_files', generated_files/u.test(hardening)],
  ["product links stay inside the exact console route", /link\.pathname === "\/console\/assistant"[\s\S]*artifact\\0edition\\0experiment/u.test(client)],
  ["browser registry is tenant and organization bounded", /tenantId: string[\s\S]*organizationId: string \| null/u.test(registry) && /workspace\.tenantId === activeTenant\.tenantId[\s\S]*workspace\.organizationId === activeTenant\.organizationId/u.test(registry)],
  ["cross-device workspace index is tenant and edition bounded", /async function handleWorkspaceIndex[\s\S]*\.eq\("owner_user_id", user\.id\)[\s\S]*\.eq\("tenant_id", tenantId\)[\s\S]*\.eq\("edition", selectedEdition\)/u.test(edge) && /parseWorkspaceIndex[\s\S]*item\.tenant_id !== expectedTenantId[\s\S]*item\.organization_id !== expectedOrganizationId[\s\S]*item\.edition !== expectedEdition/u.test(client) && /hydrateAssistantWorkspaceIndex/u.test(registry)],
  ["retry accounting does not increment twice", /assistant_claim_next_run already increments attempt_count[\s\S]*set state = case when attempt_count < max_attempts/u.test(hardening) && !/assistant_defer_run[\s\S]{0,1600}attempt_count\s*=\s*attempt_count\s*\+/u.test(hardening)],
];

const failed = checks.filter(([, passed]) => !passed);
for (const [name, passed] of checks) {
  console.log(`${passed ? "PASS" : "FAIL"} ${name}`);
}
if (failed.length) process.exitCode = 1;
