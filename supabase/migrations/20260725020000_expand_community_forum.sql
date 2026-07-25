alter table public.community_topics
  add column if not exists tags text[] not null default '{}',
  add column if not exists image_urls text[] not null default '{}';

create table if not exists public.community_comments (
  id uuid primary key default gen_random_uuid(),
  topic_id uuid not null references public.community_topics(id) on delete cascade,
  parent_id uuid references public.community_comments(id) on delete cascade,
  author_id uuid not null references auth.users(id) on delete cascade,
  author_name text not null
    check (char_length(author_name) between 1 and 48),
  body text not null
    check (char_length(body) between 1 and 2000),
  created_at timestamptz not null default timezone('utc'::text, now()),
  updated_at timestamptz not null default timezone('utc'::text, now())
);

create table if not exists public.community_topic_likes (
  topic_id uuid not null references public.community_topics(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default timezone('utc'::text, now()),
  primary key (topic_id, user_id)
);

create table if not exists public.community_comment_likes (
  comment_id uuid not null references public.community_comments(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default timezone('utc'::text, now()),
  primary key (comment_id, user_id)
);

alter table public.community_comments enable row level security;
alter table public.community_topic_likes enable row level security;
alter table public.community_comment_likes enable row level security;

revoke all on table public.community_comments from anon, authenticated;
revoke all on table public.community_topic_likes from anon, authenticated;
revoke all on table public.community_comment_likes from anon, authenticated;
grant select on table public.community_comments to anon, authenticated;
grant select on table public.community_topic_likes to anon, authenticated;
grant select on table public.community_comment_likes to anon, authenticated;
grant insert, update, delete on table public.community_comments to authenticated;
grant insert, delete on table public.community_topic_likes to authenticated;
grant insert, delete on table public.community_comment_likes to authenticated;

drop policy if exists "Community comments are publicly readable"
  on public.community_comments;
create policy "Community comments are publicly readable"
  on public.community_comments
  for select
  using (true);

drop policy if exists "Authenticated users create their own comments"
  on public.community_comments;
create policy "Authenticated users create their own comments"
  on public.community_comments
  for insert
  to authenticated
  with check (auth.uid() = author_id);

drop policy if exists "Authors update their own comments"
  on public.community_comments;
create policy "Authors update their own comments"
  on public.community_comments
  for update
  to authenticated
  using (auth.uid() = author_id)
  with check (auth.uid() = author_id);

drop policy if exists "Authors delete their own comments"
  on public.community_comments;
create policy "Authors delete their own comments"
  on public.community_comments
  for delete
  to authenticated
  using (auth.uid() = author_id);

drop policy if exists "Topic likes are publicly readable"
  on public.community_topic_likes;
create policy "Topic likes are publicly readable"
  on public.community_topic_likes
  for select
  using (true);

drop policy if exists "Users create their own topic likes"
  on public.community_topic_likes;
create policy "Users create their own topic likes"
  on public.community_topic_likes
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists "Users remove their own topic likes"
  on public.community_topic_likes;
create policy "Users remove their own topic likes"
  on public.community_topic_likes
  for delete
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists "Comment likes are publicly readable"
  on public.community_comment_likes;
create policy "Comment likes are publicly readable"
  on public.community_comment_likes
  for select
  using (true);

drop policy if exists "Users create their own comment likes"
  on public.community_comment_likes;
create policy "Users create their own comment likes"
  on public.community_comment_likes
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists "Users remove their own comment likes"
  on public.community_comment_likes;
create policy "Users remove their own comment likes"
  on public.community_comment_likes
  for delete
  to authenticated
  using (auth.uid() = user_id);

create index if not exists community_topics_tags_idx
  on public.community_topics using gin (tags);
create index if not exists community_comments_topic_created_idx
  on public.community_comments (topic_id, created_at asc);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'community-media',
  'community-media',
  true,
  8388608,
  array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Community media is publicly readable"
  on storage.objects;
create policy "Community media is publicly readable"
  on storage.objects
  for select
  using (bucket_id = 'community-media');

drop policy if exists "Users upload community media to their folder"
  on storage.objects;
create policy "Users upload community media to their folder"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'community-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "Users update community media in their folder"
  on storage.objects;
create policy "Users update community media in their folder"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'community-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'community-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "Users delete community media in their folder"
  on storage.objects;
create policy "Users delete community media in their folder"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'community-media'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

notify pgrst, 'reload schema';
