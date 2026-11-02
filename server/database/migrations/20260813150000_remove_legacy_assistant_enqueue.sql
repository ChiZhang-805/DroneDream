-- The organization-aware enqueue RPC superseded the initial personal-only
-- signature. Keeping the old overload is unsafe after tenant constraints
-- replace its inferred conflict key, and it is no longer granted to callers.

drop function if exists public.assistant_enqueue_turn(
  uuid, text, text, text, text, text, text, text, jsonb
);
