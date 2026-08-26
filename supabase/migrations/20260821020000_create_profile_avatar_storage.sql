-- Keep account avatars separate from community attachments. Each authenticated
-- account owns exactly one public JPEG at <user-id>/avatar.jpg. The bucket
-- enforces the byte and MIME limits, while RLS enforces object ownership.

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'profile-avatars',
  'profile-avatars',
  true,
  1048576,
  array['image/jpeg']
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Profile avatars are publicly readable"
  on storage.objects;
create policy "Profile avatars are publicly readable"
  on storage.objects
  for select
  using (bucket_id = 'profile-avatars');

drop policy if exists "Users insert their profile avatar"
  on storage.objects;
create policy "Users insert their profile avatar"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'profile-avatars'
    and name = auth.uid()::text || '/avatar.jpg'
  );

drop policy if exists "Users update their profile avatar"
  on storage.objects;
create policy "Users update their profile avatar"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'profile-avatars'
    and name = auth.uid()::text || '/avatar.jpg'
  )
  with check (
    bucket_id = 'profile-avatars'
    and name = auth.uid()::text || '/avatar.jpg'
  );

drop policy if exists "Users delete their profile avatar"
  on storage.objects;
create policy "Users delete their profile avatar"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'profile-avatars'
    and name = auth.uid()::text || '/avatar.jpg'
  );
