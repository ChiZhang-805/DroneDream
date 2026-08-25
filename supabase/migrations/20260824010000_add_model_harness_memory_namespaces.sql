-- Make long-term assistant memory account/tenant scoped and isolate it by the
-- Model + Harness responsibility that produced it. Edition and workspace stay
-- on each row only as source provenance; neither is a read or uniqueness key.

alter table public.console_memory_records
  add column if not exists responsibility_namespace text;

create or replace function public.console_memory_strip_task_authority(input jsonb)
returns jsonb
language plpgsql
immutable
security definer
set search_path = public, pg_temp
as $$
declare
  sanitized jsonb;
begin
  if input is null then
    return null;
  end if;
  case jsonb_typeof(input)
    when 'object' then
      select coalesce(
        jsonb_object_agg(entry.key, public.console_memory_strip_task_authority(entry.value)),
        '{}'::jsonb
      )
      into sanitized
      from jsonb_each(input) as entry
      where regexp_replace(lower(entry.key), '[^a-z0-9]', '', 'g') not in (
        'operatorapproval', 'approval', 'approved', 'isapproved',
        'approvalgranted', 'approvalstatus', 'approvalreceipt', 'approvaltoken',
        'onetimeapproval', 'onetimeconfirmation', 'confirmation', 'confirmed',
        'confirmationtoken', 'confirmationreceipt', 'executionauthorized',
        'executionauthority', 'execute', 'executenow', 'actuatorauthority',
        'flightauthority', 'vehiclecontrolauthority', 'controlauthority',
        'writeauthority', 'parameterwriteauthority', 'arm', 'armed', 'arming',
        'armingauthority'
      )
      and regexp_replace(lower(entry.key), '[^a-z0-9]', '', 'g')
        !~ '^(approval|confirmation)(granted|status|receipt|token)$'
      and regexp_replace(lower(entry.key), '[^a-z0-9]', '', 'g')
        !~ '^(actuator|flight|execution|vehiclecontrol|control|parameterwrite|write|arming)authority$';
      return sanitized;
    when 'array' then
      select coalesce(
        jsonb_agg(public.console_memory_strip_task_authority(item.value) order by item.ordinality),
        '[]'::jsonb
      )
      into sanitized
      from jsonb_array_elements(input) with ordinality as item(value, ordinality);
      return sanitized;
    else
      return input;
  end case;
end;
$$;

-- Existing rows predate responsibility namespaces. Prefer the validated
-- artifact identity and use the old scope only as a conservative fallback.
update public.console_memory_records
set responsibility_namespace = case payload ->> 'artifact_kind'
  when 'autonomy_mission_plan' then 'autonomy.mission'
  when 'external_asset_qualification_plan' then 'asset.qualification'
  when 'universal_vehicle_model' then 'asset.qualification'
  when 'universal_simulation_experiment' then 'experiment.simulation'
  when 'simulation_experiment' then 'experiment.simulation'
  when 'lab_simulation_experiment' then 'experiment.simulation'
  when 'universal_cross_edition_workflow' then 'workflow.cross_edition'
  when 'lab_hardware_validation' then 'validation.hardware'
  when 'lab_calibration_workflow' then 'calibration.system'
  when 'lab_sim_to_real_workflow' then 'transfer.sim_to_real'
  when 'lab_real_to_sim_workflow' then 'transfer.real_to_sim'
  when 'field_task_plan' then 'operations.field'
  else case scope
    when 'chat_preferences' then 'account.shared'
    when 'reports_delivery' then 'account.shared'
    when 'collaboration_organization' then 'account.shared'
    when 'metrics_constraints' then 'optimization.control_tuning'
    when 'experiment_defaults' then 'experiment.simulation'
    when 'device_vehicle' then 'asset.qualification'
    when 'files_artifacts' then 'asset.qualification'
    when 'safety_approvals' then 'validation.hardware'
    when 'workflow_tools' then 'workflow.cross_edition'
    else 'experiment.simulation'
  end
end
where responsibility_namespace is null;

-- Scrub legacy long-term records and stored defaults before any cross-edition
-- read can occur. Required-approval policies remain valid; granted approval,
-- one-time confirmation, arming/write state, and execution authority do not.
update public.console_memory_records
set payload = public.console_memory_strip_task_authority(payload);

update public.console_preferences
set defaults = public.console_memory_strip_task_authority(defaults);

alter table public.console_memory_records
  alter column responsibility_namespace drop default,
  alter column responsibility_namespace set not null;

alter table public.console_memory_records
  drop constraint if exists console_memory_records_responsibility_namespace_check;
alter table public.console_memory_records
  add constraint console_memory_records_responsibility_namespace_check check (
    responsibility_namespace in (
      'account.shared',
      'optimization.control_tuning',
      'autonomy.mission',
      'asset.qualification',
      'experiment.simulation',
      'workflow.cross_edition',
      'validation.hardware',
      'calibration.system',
      'transfer.sim_to_real',
      'transfer.real_to_sim',
      'operations.field'
    )
  );

-- Older clients may omit the new column. Derive a conservative namespace from
-- their artifact/scope while enforcing the same authority scrub on every write.
create or replace function public.console_memory_enforce_contract()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  new.payload := public.console_memory_strip_task_authority(new.payload);
  if new.responsibility_namespace is null then
    new.responsibility_namespace := case new.payload ->> 'artifact_kind'
      when 'autonomy_mission_plan' then 'autonomy.mission'
      when 'external_asset_qualification_plan' then 'asset.qualification'
      when 'universal_vehicle_model' then 'asset.qualification'
      when 'universal_simulation_experiment' then 'experiment.simulation'
      when 'simulation_experiment' then 'experiment.simulation'
      when 'lab_simulation_experiment' then 'experiment.simulation'
      when 'universal_cross_edition_workflow' then 'workflow.cross_edition'
      when 'lab_hardware_validation' then 'validation.hardware'
      when 'lab_calibration_workflow' then 'calibration.system'
      when 'lab_sim_to_real_workflow' then 'transfer.sim_to_real'
      when 'lab_real_to_sim_workflow' then 'transfer.real_to_sim'
      when 'field_task_plan' then 'operations.field'
      else case new.scope
        when 'chat_preferences' then 'account.shared'
        when 'reports_delivery' then 'account.shared'
        when 'collaboration_organization' then 'account.shared'
        when 'metrics_constraints' then 'optimization.control_tuning'
        when 'experiment_defaults' then 'experiment.simulation'
        when 'device_vehicle' then 'asset.qualification'
        when 'files_artifacts' then 'asset.qualification'
        when 'safety_approvals' then 'validation.hardware'
        when 'workflow_tools' then 'workflow.cross_edition'
        else 'experiment.simulation'
      end
    end;
  end if;
  return new;
end;
$$;

drop trigger if exists console_memory_enforce_contract on public.console_memory_records;
create trigger console_memory_enforce_contract
  before insert or update of responsibility_namespace, scope, payload
  on public.console_memory_records
  for each row execute function public.console_memory_enforce_contract();

drop index if exists public.console_memory_records_boundary_idx;
create index if not exists console_memory_records_account_namespace_idx
  on public.console_memory_records (
    user_id, tenant_id, organization_id, responsibility_namespace, scope, updated_at desc
  );

comment on column public.console_memory_records.responsibility_namespace is
  'Canonical Model + Harness responsibility boundary shared across editions for one account and tenant.';
comment on column public.console_memory_records.edition is
  'Source edition metadata only; never a long-term-memory read or uniqueness boundary.';
comment on column public.console_memory_records.workspace_id is
  'Source workspace metadata only; never a long-term-memory read or uniqueness boundary.';
comment on column public.console_memory_records.conversation_id is
  'Optional source provenance only; conversation messages and summaries remain conversation-isolated.';

-- Authenticated access fails closed on both the account and resolved tenant.
-- Organization rows additionally require an active membership. Service-role
-- orchestration still repeats the same predicates in every query.
alter table public.console_memory_records enable row level security;
alter table public.console_memory_records force row level security;

drop policy if exists "Users manage their bounded console memory" on public.console_memory_records;
create policy "Users manage their bounded console memory"
  on public.console_memory_records for all to authenticated
  using (
    user_id = auth.uid() and (
      (
        organization_id = '00000000-0000-0000-0000-000000000000'
        and tenant_id = auth.uid()
      )
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_records.organization_id
          and membership.organization_id = console_memory_records.tenant_id
          and membership.user_id = auth.uid()
          and membership.status = 'active'
      )
    )
  )
  with check (
    user_id = auth.uid() and (
      (
        organization_id = '00000000-0000-0000-0000-000000000000'
        and tenant_id = auth.uid()
      )
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_records.organization_id
          and membership.organization_id = console_memory_records.tenant_id
          and membership.user_id = auth.uid()
          and membership.status = 'active'
      )
    )
  );

revoke all on function public.console_memory_strip_task_authority(jsonb)
  from public, anon, authenticated;
revoke all on function public.console_memory_enforce_contract()
  from public, anon, authenticated;
grant execute on function public.console_memory_strip_task_authority(jsonb) to service_role;
grant execute on function public.console_memory_enforce_contract() to service_role;
revoke all on public.console_memory_records from anon;
grant select, insert, update, delete on public.console_memory_records to authenticated;
grant all on public.console_memory_records to service_role;
