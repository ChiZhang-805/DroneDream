-- Extend the bounded, account-scoped memory contract with collaboration and
-- generated-artifact preferences. RLS remains unchanged and continues to bind
-- every record to user, tenant, organization, workspace, and edition.

alter table public.console_memory_records
  drop constraint if exists console_memory_records_scope_check;

alter table public.console_memory_records
  add constraint console_memory_records_scope_check check (scope in (
    'chat_preferences', 'experiment_defaults', 'device_vehicle',
    'metrics_constraints', 'safety_approvals', 'workflow_tools',
    'reports_delivery', 'collaboration_organization', 'files_artifacts'
  ));
