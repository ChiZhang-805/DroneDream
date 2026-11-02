-- Remove the retired community catalog before the new English card set is authored.
-- Topic comments and likes are removed by their existing cascading foreign keys.
delete from public.community_topics;
