-- Keep forum relationships and server-owned metadata trustworthy even when a
-- signed-in user calls the Data API directly instead of using the website UI.

alter table public.community_topics
  drop constraint if exists community_topics_tags_limit,
  drop constraint if exists community_topics_image_urls_limit;

alter table public.community_topics
  add constraint community_topics_tags_limit
    check (cardinality(tags) <= 5),
  add constraint community_topics_image_urls_limit
    check (cardinality(image_urls) <= 4);

alter table public.community_comments
  drop constraint if exists community_comments_parent_not_self;

alter table public.community_comments
  add constraint community_comments_parent_not_self
    check (parent_id is null or parent_id <> id);

-- PostgreSQL requires a matching unique key for the composite parent
-- reference. The primary key already makes id unique; this additional key
-- lets the foreign key also prove that the parent belongs to the same topic.
alter table public.community_comments
  add constraint community_comments_id_topic_unique unique (id, topic_id);

alter table public.community_comments
  drop constraint if exists community_comments_parent_id_fkey;

alter table public.community_comments
  add constraint community_comments_parent_same_topic_fkey
    foreign key (parent_id, topic_id)
    references public.community_comments (id, topic_id)
    on delete cascade;

create or replace function public.community_set_server_timestamps()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.created_at := timezone('utc'::text, now());
  else
    new.created_at := old.created_at;
  end if;
  new.updated_at := timezone('utc'::text, now());
  return new;
end;
$$;

revoke all on function public.community_set_server_timestamps() from public;

drop trigger if exists community_topics_server_timestamps
  on public.community_topics;
create trigger community_topics_server_timestamps
  before insert or update on public.community_topics
  for each row execute function public.community_set_server_timestamps();

drop trigger if exists community_comments_server_timestamps
  on public.community_comments;
create trigger community_comments_server_timestamps
  before insert or update on public.community_comments
  for each row execute function public.community_set_server_timestamps();

notify pgrst, 'reload schema';
