create table if not exists public.community_topics (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references auth.users(id) on delete cascade,
  author_name text not null
    check (char_length(author_name) between 1 and 48),
  title text not null
    check (char_length(title) between 1 and 120),
  body text not null
    check (char_length(body) between 12 and 4000),
  created_at timestamptz not null default timezone('utc'::text, now()),
  updated_at timestamptz not null default timezone('utc'::text, now())
);

alter table public.community_topics enable row level security;

revoke all on table public.community_topics from anon, authenticated;
grant select on table public.community_topics to anon, authenticated;
grant insert, update, delete on table public.community_topics to authenticated;

drop policy if exists "Community topics are publicly readable"
  on public.community_topics;
create policy "Community topics are publicly readable"
  on public.community_topics
  for select
  using (true);

drop policy if exists "Authenticated users create their own topics"
  on public.community_topics;
create policy "Authenticated users create their own topics"
  on public.community_topics
  for insert
  to authenticated
  with check (auth.uid() = author_id);

drop policy if exists "Authors update their own topics"
  on public.community_topics;
create policy "Authors update their own topics"
  on public.community_topics
  for update
  to authenticated
  using (auth.uid() = author_id)
  with check (auth.uid() = author_id);

drop policy if exists "Authors delete their own topics"
  on public.community_topics;
create policy "Authors delete their own topics"
  on public.community_topics
  for delete
  to authenticated
  using (auth.uid() = author_id);

create index if not exists community_topics_created_at_idx
  on public.community_topics (created_at desc);

notify pgrst, 'reload schema';
