-- Give AUTONOMY its own immutable Vehicle Studio namespace while preserving
-- Universal's existing rows and tenant RLS boundary.
alter table public.vehicle_model_revisions
  drop constraint if exists vehicle_model_revisions_workspace_id_check;
alter table public.vehicle_model_revisions
  drop constraint if exists vehicle_model_revisions_edition_check;

alter table public.vehicle_model_revisions
  add constraint vehicle_model_revisions_workspace_edition_check check (
    (edition = 'universal' and workspace_id = 'console-universal')
    or (edition = 'autonomy' and workspace_id = 'console-autonomy')
  );
