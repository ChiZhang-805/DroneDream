-- Exact topic counts for the ten-card discovery pager. Keep the search and
-- filter predicate aligned with community_list_topics so page totals never
-- leak hidden rows or disagree with the visible result set.
create or replace function public.community_count_topics(
  p_search text default null,
  p_tag text default null
)
returns bigint
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
  select count(*)
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
    );
$$;

revoke all on function public.community_count_topics(text, text) from public;
grant execute on function public.community_count_topics(text, text) to anon, authenticated;

notify pgrst, 'reload schema';
