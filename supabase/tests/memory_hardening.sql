begin;
create extension if not exists pgtap with schema extensions;
select plan(30);

select has_table('public', 'console_memory_consents', 'account-wide memory consent exists');
select has_table('public', 'console_memory_deletion_tombstones', 'payload-free deletion tombstones exist');
select has_column('public', 'console_memory_candidates', 'source_receipt_id', 'candidates bind a source receipt');
select has_column('public', 'console_memory_candidates', 'source_receipt_verified_at', 'source receipt verification is persisted');
select has_trigger(
  'public',
  'console_memory_candidates',
  'console_memory_candidates_require_write_consent',
  'candidate inserts require account write consent'
);
select has_trigger(
  'public',
  'console_memory_records',
  'console_memory_records_require_write_consent',
  'consolidated memory inserts require account write consent'
);
select has_function(
  'public',
  'console_memory_permanently_delete_current_user',
  array['uuid', 'uuid', 'text', 'text', 'text'],
  'scoped permanent delete RPC exists'
);
select has_function(
  'public',
  'console_memory_permanently_delete_all_current_user',
  array['uuid', 'uuid'],
  'atomic account-wide permanent delete RPC exists'
);
select has_column(
  'public', 'console_memory_records', 'projection_revision',
  'cloud records expose a monotonic desktop projection revision'
);
select has_function(
  'public',
  'console_memory_stage_current_user',
  array[
    'uuid', 'uuid', 'text', 'text', 'text', 'text', 'jsonb', 'text', 'text',
    'uuid', 'uuid', 'text', 'text', 'jsonb', 'jsonb', 'text', 'numeric'
  ],
  'authenticated desktop staging RPC exists'
);
select ok(
  position('caller_user_id uuid := auth.uid()' in lower(pg_get_functiondef(
    'public.console_memory_stage_current_user(uuid,uuid,text,text,text,text,jsonb,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) > 0,
  'desktop staging derives the owner from auth.uid()'
);
select ok(
  position('''validated_plan_candidate''' in lower(pg_get_functiondef(
    'public.console_memory_stage_current_user(uuid,uuid,text,text,text,text,jsonb,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) > 0
  and position('''explicit_user_update''' in lower(pg_get_functiondef(
    'public.console_memory_stage_current_user(uuid,uuid,text,text,text,text,jsonb,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) = 0,
  'desktop staging cannot self-promote cloud memory'
);
select ok(
  position('lock table' in lower(pg_get_functiondef(
    'public.console_memory_forget_current_user(uuid,uuid,text,text,text)'::regprocedure
  ))) = 0,
  'authenticated soft forget never takes a table lock'
);
select ok(
  position('pg_advisory_xact_lock' in lower(pg_get_functiondef(
    'public.console_memory_forget_current_user(uuid,uuid,text,text,text)'::regprocedure
  ))) > 0,
  'authenticated soft forget uses scoped advisory locking'
);
select ok(
  position('group by candidate.conversation_id' in lower(pg_get_functiondef(
    'public.console_memory_stage_candidate(uuid,uuid,uuid,text,text,text,text,jsonb,text,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) > 0,
  'candidate support counts distinct conversations'
);
select ok(
  position('support_count >= greatest' in lower(pg_get_functiondef(
    'public.console_memory_stage_candidate(uuid,uuid,uuid,text,text,text,text,jsonb,text,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) = 0,
  'active conflicts cannot auto-supersede memory'
);
select ok(
  position('p_source_kind = ''explicit_user_update''' in lower(pg_get_functiondef(
    'public.console_memory_stage_candidate(uuid,uuid,uuid,text,text,text,text,jsonb,text,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) > 0,
  'only direct explicit user updates may self-promote'
);
select ok(
  position('p_source_kind = ''validated_plan_candidate'' and support_confidence' in lower(pg_get_functiondef(
    'public.console_memory_stage_candidate(uuid,uuid,uuid,text,text,text,text,jsonb,text,text,text,uuid,uuid,text,text,jsonb,jsonb,text,numeric)'::regprocedure
  ))) = 0,
  'model-generated plan candidates never self-promote'
);
select ok(
  position('set memory_enabled = false' in lower(pg_get_functiondef(
    'public.console_memory_permanently_delete_all_current_user(uuid,uuid)'::regprocedure
  ))) > 0,
  'account-wide deletion closes the write gate in the same transaction'
);

select has_column(
  'public', 'console_memory_deletion_tombstones', 'released_at',
  'tombstones retain the time of an explicit relearn release'
);
select has_column(
  'public', 'console_memory_deletion_tombstones', 'released_by',
  'tombstones retain the authenticated relearn actor'
);
select has_column(
  'public', 'console_memory_deletion_tombstones', 'release_reason',
  'tombstones retain the controlled release reason'
);
select has_function(
  'public',
  'console_memory_release_deletion_tombstone_current_user',
  array['uuid', 'uuid', 'text', 'text', 'text', 'boolean'],
  'authenticated explicit relearn RPC exists'
);
select ok(
  position('memory_scope_tombstoned' in lower(pg_get_functiondef(
    'public.console_memory_require_write_consent()'::regprocedure
  ))) > 0,
  'the database write gate rejects an active deletion tombstone'
);
select ok(
  position('tombstone.released_at is null' in lower(pg_get_functiondef(
    'public.console_memory_require_write_consent()'::regprocedure
  ))) > 0,
  'only an explicitly released tombstone stops blocking writes'
);
select ok(
  position('tombstone.responsibility_namespace = ''account.all''' in lower(pg_get_functiondef(
    'public.console_memory_require_write_consent()'::regprocedure
  ))) > 0,
  'account-wide deletion blocks writes in every responsibility namespace'
);
select ok(
  position('digest(convert_to(new.memory_key, ''UTF8''), ''sha256'')' in pg_get_functiondef(
    'public.console_memory_require_write_consent()'::regprocedure
  )) > 0,
  'field tombstones compare only a payload-free memory-key digest'
);
select ok(
  position('consent.memory_scopes @> jsonb_build_object(new.scope, true)' in lower(pg_get_functiondef(
    'public.console_memory_require_write_consent()'::regprocedure
  ))) > 0,
  'write consent is fail-closed for the exact memory scope'
);
select ok(
  position('p_confirm_relearn is distinct from true' in lower(pg_get_functiondef(
    'public.console_memory_release_deletion_tombstone_current_user(uuid,uuid,text,text,text,boolean)'::regprocedure
  ))) > 0
  and position('consent.memory_enabled' in lower(pg_get_functiondef(
    'public.console_memory_release_deletion_tombstone_current_user(uuid,uuid,text,text,text,boolean)'::regprocedure
  ))) > 0
  and position('memory_reconsent_required' in lower(pg_get_functiondef(
    'public.console_memory_release_deletion_tombstone_current_user(uuid,uuid,text,text,text,boolean)'::regprocedure
  ))) > 0,
  'release requires affirmative confirmation after consent is restored'
);
select ok(
  position('delete from public.console_memory_deletion_tombstones' in lower(pg_get_functiondef(
    'public.console_memory_release_deletion_tombstone_current_user(uuid,uuid,text,text,text,boolean)'::regprocedure
  ))) = 0
  and position('release_reason = ''explicit_reconsent''' in lower(pg_get_functiondef(
    'public.console_memory_release_deletion_tombstone_current_user(uuid,uuid,text,text,text,boolean)'::regprocedure
  ))) > 0,
  'relearn annotates rather than erases the deletion audit record'
);

select * from finish();
rollback;
