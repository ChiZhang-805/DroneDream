-- Public-launch read paths and write guards for the community.
--
-- The website must not download every comment and like row in order to render
-- a page. These security-invoker functions keep RLS authoritative while
-- returning bounded pages with aggregate counts.

create or replace function public.community_list_topics(
  p_search text default null,
  p_tag text default null,
  p_offset integer default 0,
  p_limit integer default 24
)
returns table (
  id uuid,
  author_id uuid,
  author_name text,
  title text,
  body text,
  tags text[],
  image_urls text[],
  created_at timestamptz,
  comment_count bigint,
  like_count bigint,
  liked_by_viewer boolean
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    topic.id,
    topic.author_id,
    topic.author_name,
    topic.title,
    topic.body,
    topic.tags,
    topic.image_urls,
    topic.created_at,
    (
      select count(*)
      from public.community_comments as comment
      where comment.topic_id = topic.id
    ) as comment_count,
    (
      select count(*)
      from public.community_topic_likes as topic_like
      where topic_like.topic_id = topic.id
    ) as like_count,
    exists (
      select 1
      from public.community_topic_likes as viewer_like
      where viewer_like.topic_id = topic.id
        and viewer_like.user_id = auth.uid()
    ) as liked_by_viewer
  from public.community_topics as topic
  where (
      nullif(btrim(p_search), '') is null
      or topic.title ilike '%' || btrim(p_search) || '%'
      or topic.body ilike '%' || btrim(p_search) || '%'
      or array_to_string(topic.tags, ' ') ilike '%' || btrim(p_search) || '%'
    )
    and (
      nullif(btrim(p_tag), '') is null
      or btrim(p_tag) = any(topic.tags)
    )
  order by topic.created_at desc, topic.id desc
  offset greatest(coalesce(p_offset, 0), 0)
  limit least(greatest(coalesce(p_limit, 24), 1), 50);
$$;

create or replace function public.community_list_comments(
  p_topic_id uuid,
  p_offset integer default 0,
  p_limit integer default 100
)
returns table (
  id uuid,
  topic_id uuid,
  parent_id uuid,
  parent_author_name text,
  author_id uuid,
  author_name text,
  body text,
  created_at timestamptz,
  like_count bigint,
  liked_by_viewer boolean
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    comment.id,
    comment.topic_id,
    comment.parent_id,
    parent.author_name as parent_author_name,
    comment.author_id,
    comment.author_name,
    comment.body,
    comment.created_at,
    (
      select count(*)
      from public.community_comment_likes as comment_like
      where comment_like.comment_id = comment.id
    ) as like_count,
    exists (
      select 1
      from public.community_comment_likes as viewer_like
      where viewer_like.comment_id = comment.id
        and viewer_like.user_id = auth.uid()
    ) as liked_by_viewer
  from public.community_comments as comment
  left join public.community_comments as parent
    on parent.id = comment.parent_id
    and parent.topic_id = comment.topic_id
  where comment.topic_id = p_topic_id
  order by comment.created_at asc, comment.id asc
  offset greatest(coalesce(p_offset, 0), 0)
  limit least(greatest(coalesce(p_limit, 100), 1), 200);
$$;

revoke all on function public.community_list_topics(text, text, integer, integer)
  from public;
grant execute on function public.community_list_topics(text, text, integer, integer)
  to anon, authenticated;

revoke all on function public.community_list_comments(uuid, integer, integer)
  from public;
grant execute on function public.community_list_comments(uuid, integer, integer)
  to anon, authenticated;

-- Direct Data API clients must obey the same ownership and rate rules as the
-- website. The trigger also derives the visible author name from trusted Auth
-- metadata so callers cannot impersonate another community member.
create or replace function public.community_guard_write()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
  trusted_author_name text;
  recent_count integer;
  daily_count integer;
begin
  if auth.role() = 'service_role' then
    return new;
  end if;

  if current_user_id is null or new.author_id <> current_user_id then
    raise exception 'Community writes require the signed-in user identity.'
      using errcode = '42501';
  end if;

  select left(
    coalesce(
      nullif(btrim(user_row.raw_user_meta_data ->> 'display_name'), ''),
      nullif(split_part(user_row.email, '@', 1), ''),
      'DroneDream user'
    ),
    48
  )
  into trusted_author_name
  from auth.users as user_row
  where user_row.id = current_user_id;

  if tg_table_name = 'community_topics' then
    select
      count(*) filter (
        where topic.created_at >= timezone('utc'::text, now()) - interval '1 hour'
      ),
      count(*) filter (
        where topic.created_at >= timezone('utc'::text, now()) - interval '1 day'
      )
    into recent_count, daily_count
    from public.community_topics as topic
    where topic.author_id = current_user_id;

    if recent_count >= 5 or daily_count >= 20 then
      raise exception 'Topic publishing limit reached. Please try again later.'
        using errcode = 'P0001';
    end if;
  elsif tg_table_name = 'community_comments' then
    select
      count(*) filter (
        where comment.created_at >= timezone('utc'::text, now()) - interval '1 hour'
      ),
      count(*) filter (
        where comment.created_at >= timezone('utc'::text, now()) - interval '1 day'
      )
    into recent_count, daily_count
    from public.community_comments as comment
    where comment.author_id = current_user_id;

    if recent_count >= 30 or daily_count >= 100 then
      raise exception 'Comment publishing limit reached. Please try again later.'
        using errcode = 'P0001';
    end if;
  else
    raise exception 'Unsupported community write target.'
      using errcode = 'P0001';
  end if;

  new.author_name := trusted_author_name;
  return new;
end;
$$;

revoke all on function public.community_guard_write() from public;

drop trigger if exists community_topics_guard_write
  on public.community_topics;
create trigger community_topics_guard_write
  before insert on public.community_topics
  for each row execute function public.community_guard_write();

drop trigger if exists community_comments_guard_write
  on public.community_comments;
create trigger community_comments_guard_write
  before insert on public.community_comments
  for each row execute function public.community_guard_write();

notify pgrst, 'reload schema';
