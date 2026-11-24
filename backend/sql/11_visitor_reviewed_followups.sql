begin;

create or replace function public.visitor_followup_questions(exhibition_id uuid, artwork_id uuid, how_level text)
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'question_id', q.id, 'question', q.question, 'category', q.category,
    'priority', q.priority, 'answer', q.answers_by_how->>how_level
  ) order by q.priority, q.id), '[]'::jsonb)
  from public.followup_questions q
  join public.artworks a on a.id = q.artwork_id
  join public.exhibitions e on e.id = a.exhibition_id
  where e.is_public and e.id = $1 and a.id = $2
    and how_level in ('Basic', 'Advanced')
    and q.review_status in ('reviewed', 'published') and not q.needs_recheck
    and length(btrim(q.answers_by_how->>'Basic')) > 0
    and length(btrim(q.answers_by_how->>'Advanced')) > 0
    and public.followup_evidence_valid(q.artwork_id, q.related_unit_ids, false);
$$;
revoke all on function public.visitor_followup_questions(uuid, uuid, text) from public;
grant execute on function public.visitor_followup_questions(uuid, uuid, text) to anon, authenticated;

commit;
