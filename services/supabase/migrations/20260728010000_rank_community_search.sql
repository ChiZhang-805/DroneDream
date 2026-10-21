-- Ranked, typo-tolerant community search.
--
-- Full-text search handles multi-word intent and quoted phrases. Trigram
-- similarity preserves useful results for partial terms and small spelling
-- mistakes, while substring matching remains important for Chinese text and
-- engineering identifiers such as PX4 parameter names.

create extension if not exists pg_trgm with schema extensions;

alter table public.community_topics
  add column if not exists search_document tsvector;

create or replace function public.community_refresh_topic_search_document()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.search_document :=
    setweight(
      to_tsvector('simple'::regconfig, coalesce(new.title, '')),
      'A'
    )
    ||
    setweight(
      to_tsvector(
        'simple'::regconfig,
        coalesce(array_to_string(new.tags, ' '), '')
      ),
      'A'
    )
    ||
    setweight(
      to_tsvector('simple'::regconfig, coalesce(new.body, '')),
      'B'
    );
  return new;
end;
$$;

revoke all on function public.community_refresh_topic_search_document()
  from public;

drop trigger if exists community_topics_refresh_search_document
  on public.community_topics;
create trigger community_topics_refresh_search_document
  before insert or update of title, body, tags
  on public.community_topics
  for each row execute function public.community_refresh_topic_search_document();

update public.community_topics
set search_document =
  setweight(
    to_tsvector('simple'::regconfig, coalesce(title, '')),
    'A'
  )
  ||
  setweight(
    to_tsvector(
      'simple'::regconfig,
      coalesce(array_to_string(tags, ' '), '')
    ),
    'A'
  )
  ||
  setweight(
    to_tsvector('simple'::regconfig, coalesce(body, '')),
    'B'
  );

alter table public.community_topics
  alter column search_document set not null;

create index if not exists community_topics_search_document_idx
  on public.community_topics using gin (search_document);

create index if not exists community_topics_title_trgm_idx
  on public.community_topics using gin (title extensions.gin_trgm_ops);

create index if not exists community_topics_body_trgm_idx
  on public.community_topics using gin (body extensions.gin_trgm_ops);

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
  with search_input as (
    select
      nullif(btrim(p_search), '') as query_text,
      websearch_to_tsquery(
        'simple'::regconfig,
        coalesce(nullif(btrim(p_search), ''), '')
      ) as web_query
  )
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
  cross join search_input
  where (
      search_input.query_text is null
      or topic.search_document @@ search_input.web_query
      or topic.title ilike '%' || search_input.query_text || '%'
      or topic.body ilike '%' || search_input.query_text || '%'
      or array_to_string(topic.tags, ' ')
        ilike '%' || search_input.query_text || '%'
      or extensions.word_similarity(
        search_input.query_text,
        topic.title
      ) >= 0.42
    )
    and (
      nullif(btrim(p_tag), '') is null
      or btrim(p_tag) = any(topic.tags)
    )
  order by
    case
      when search_input.query_text is null then 0
      else
        (
          case
            when lower(topic.title) = lower(search_input.query_text) then 6.0
            when topic.title ilike search_input.query_text || '%' then 4.0
            when topic.title ilike '%' || search_input.query_text || '%' then 2.0
            else 0.0
          end
          + (4.0 * ts_rank_cd(topic.search_document, search_input.web_query, 32))
          + (2.0 * extensions.word_similarity(search_input.query_text, topic.title))
          + case
              when search_input.query_text = any(topic.tags) then 2.0
              else 0.0
            end
        )
    end desc,
    topic.created_at desc,
    topic.id desc
  offset greatest(coalesce(p_offset, 0), 0)
  limit least(greatest(coalesce(p_limit, 24), 1), 50);
$$;

revoke all on function public.community_list_topics(text, text, integer, integer)
  from public;
grant execute on function public.community_list_topics(text, text, integer, integer)
  to anon, authenticated;

notify pgrst, 'reload schema';
