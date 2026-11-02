-- Bound public community media before launch. The free project has 1 GB of
-- file storage, so uploads are compressed client-side and enforced again here.

update storage.buckets
set
  file_size_limit = 1048576,
  allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp']
where id = 'community-media';

create or replace function public.community_media_upload_allowed(
  object_name text,
  object_metadata jsonb
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
  incoming_size bigint;
  daily_uploads bigint;
  user_bytes bigint;
  global_bytes bigint;
begin
  if current_user_id is null then
    return false;
  end if;

  if (storage.foldername(object_name))[1] <> current_user_id::text then
    return false;
  end if;

  if coalesce(object_metadata ->> 'size', '') !~ '^[0-9]+$' then
    return false;
  end if;
  incoming_size := (object_metadata ->> 'size')::bigint;
  if incoming_size <= 0 or incoming_size > 1048576 then
    return false;
  end if;

  select
    count(*) filter (
      where object.created_at >= timezone('utc'::text, now()) - interval '1 day'
        and (storage.foldername(object.name))[1] = current_user_id::text
    ),
    coalesce(sum(
      case
        when (storage.foldername(object.name))[1] = current_user_id::text
          and coalesce(object.metadata ->> 'size', '') ~ '^[0-9]+$'
        then (object.metadata ->> 'size')::bigint
        else 0
      end
    ), 0),
    coalesce(sum(
      case
        when coalesce(object.metadata ->> 'size', '') ~ '^[0-9]+$'
        then (object.metadata ->> 'size')::bigint
        else 0
      end
    ), 0)
  into daily_uploads, user_bytes, global_bytes
  from storage.objects as object
  where object.bucket_id = 'community-media';

  return
    daily_uploads < 12
    and user_bytes + incoming_size <= 26214400
    and global_bytes + incoming_size <= 891289600;
end;
$$;

revoke all on function public.community_media_upload_allowed(text, jsonb)
  from public;
grant execute on function public.community_media_upload_allowed(text, jsonb)
  to authenticated;

drop policy if exists "Users upload community media to their folder"
  on storage.objects;
create policy "Users upload bounded community media"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'community-media'
    and public.community_media_upload_allowed(name, metadata)
  );

drop policy if exists "Users update community media in their folder"
  on storage.objects;
create policy "Users update bounded community media"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'community-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'community-media'
    and public.community_media_upload_allowed(name, metadata)
  );
