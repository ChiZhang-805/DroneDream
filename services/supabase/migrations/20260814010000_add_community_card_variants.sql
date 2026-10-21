-- Preserve the card selected in the topic composer and expose a safe public
-- avatar URL when the account provider already supplies one.

alter table public.community_topics
  add column if not exists card_variant text not null default 'auto';

alter table public.community_topics
  drop constraint if exists community_topics_card_variant_check;

alter table public.community_topics
  add constraint community_topics_card_variant_check
    check (card_variant in ('auto', 'short', 'long'));

create or replace function public.community_list_topics_v2(
  p_search text default null,
  p_tag text default null,
  p_offset integer default 0,
  p_limit integer default 24
)
returns table (
  id uuid,
  author_id uuid,
  author_name text,
  author_avatar_url text,
  title text,
  body text,
  tags text[],
  image_urls text[],
  created_at timestamptz,
  comment_count bigint,
  like_count bigint,
  liked_by_viewer boolean,
  card_variant text
)
language sql
stable
security definer
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
    case
      when coalesce(
        nullif(author.raw_user_meta_data ->> 'avatar_url', ''),
        nullif(author.raw_user_meta_data ->> 'picture', '')
      ) ~ '^https://'
      then coalesce(
        nullif(author.raw_user_meta_data ->> 'avatar_url', ''),
        nullif(author.raw_user_meta_data ->> 'picture', '')
      )
      else null
    end as author_avatar_url,
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
    ) as liked_by_viewer,
    topic.card_variant
  from public.community_topics as topic
  left join auth.users as author on author.id = topic.author_id
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

revoke all on function public.community_list_topics_v2(text, text, integer, integer)
  from public;
grant execute on function public.community_list_topics_v2(text, text, integer, integer)
  to anon, authenticated;

notify pgrst, 'reload schema';
