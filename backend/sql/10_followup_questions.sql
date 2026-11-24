begin;

create table public.followup_questions (
  id uuid primary key default gen_random_uuid(),
  artwork_id uuid not null references public.artworks(id) on delete cascade,
  question text not null check (length(btrim(question)) between 1 and 300),
  category text not null check (category in ('VISUAL', 'MEANING', 'TECHNIQUE', 'BACKGROUND')),
  related_unit_ids uuid[] not null check (cardinality(related_unit_ids) between 1 and 8),
  priority integer not null check (priority between 1 and 100),
  answers_by_how jsonb not null default '{}'::jsonb,
  review_status text not null default 'pending' check (review_status in ('pending', 'reviewed', 'published')),
  needs_recheck boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (jsonb_typeof(answers_by_how) = 'object' and answers_by_how - 'Basic' - 'Advanced' = '{}'::jsonb),
  check (not answers_by_how ? 'Basic' or (jsonb_typeof(answers_by_how->'Basic') = 'string'
    and length(btrim(answers_by_how->>'Basic')) between 1 and 1600)),
  check (not answers_by_how ? 'Advanced' or (jsonb_typeof(answers_by_how->'Advanced') = 'string'
    and length(btrim(answers_by_how->>'Advanced')) between 1 and 1600))
);
create index followup_artwork_status on public.followup_questions(artwork_id, review_status);
create index followup_related_units on public.followup_questions using gin(related_unit_ids);
create unique index followup_unique_question on public.followup_questions (
  artwork_id, (regexp_replace(lower(question), '[[:space:][:punct:]]', '', 'g'))
);

alter table public.followup_questions enable row level security;
revoke all on public.followup_questions from public, anon, authenticated;
grant select, insert, update, delete on public.followup_questions to authenticated;
create policy followup_admin on public.followup_questions for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));

create function public.followup_evidence_valid(target_artwork uuid, unit_ids uuid[], require_published boolean)
returns boolean language sql stable security invoker set search_path = '' as $$
  select cardinality(unit_ids) > 0 and cardinality(unit_ids) = (
    select count(*) from public.content_units u
    where u.id = any(unit_ids) and u.artwork_id = target_artwork
      and (u.status = 'published' or (not require_published and u.status = 'reviewed'))
  );
$$;
revoke all on function public.followup_evidence_valid(uuid, uuid[], boolean) from public, anon;
grant execute on function public.followup_evidence_valid(uuid, uuid[], boolean) to authenticated;

create function public.followup_status_guard()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.review_status := 'pending';
  elsif (new.question, new.category, new.related_unit_ids, new.priority, new.answers_by_how, new.artwork_id)
      is distinct from (old.question, old.category, old.related_unit_ids, old.priority, old.answers_by_how, old.artwork_id) then
    new.review_status := 'pending';
  elsif new.review_status is distinct from old.review_status and new.review_status <> 'pending' then
    if (new.review_status = 'published' and old.review_status <> 'reviewed')
        or coalesce(length(btrim(new.answers_by_how->>'Basic')), 0) = 0
        or coalesce(length(btrim(new.answers_by_how->>'Advanced')), 0) = 0
        or not public.followup_evidence_valid(new.artwork_id, new.related_unit_ids, new.review_status = 'published') then
      raise sqlstate 'PT422' using message = 'Both answers and valid evidence are required.';
    end if;
    new.needs_recheck := false;
  end if;
  new.updated_at := clock_timestamp();
  return new;
end;
$$;
create trigger followup_status before insert or update on public.followup_questions
for each row execute function public.followup_status_guard();

create function public.followup_recheck_after_unit_change()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'DELETE' or (old.content, old.category, old.artwork_id)
      is distinct from (new.content, new.category, new.artwork_id)
      or (old.status <> 'pending' and new.status = 'pending') then
    update public.followup_questions
    set review_status = 'pending', needs_recheck = true
    where related_unit_ids @> array[old.id] and artwork_id = old.artwork_id;
  end if;
  return null;
end;
$$;
create trigger followup_unit_change after update or delete on public.content_units
for each row execute function public.followup_recheck_after_unit_change();

-- The public entry point exposes only the answer for the requested HOW.
create function public.visitor_followup_questions(exhibition_id uuid, artwork_id uuid, how_level text)
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
    and q.review_status = 'published' and not q.needs_recheck
    and length(btrim(q.answers_by_how->>'Basic')) > 0
    and length(btrim(q.answers_by_how->>'Advanced')) > 0
    and public.followup_evidence_valid(q.artwork_id, q.related_unit_ids, true);
$$;
revoke all on function public.visitor_followup_questions(uuid, uuid, text) from public;
grant execute on function public.visitor_followup_questions(uuid, uuid, text) to anon, authenticated;

-- Apply a generated batch only if the pool and its evidence still match the inputs.
create function public.store_followup_generation(
  target_artwork uuid, expected_pool jsonb, expected_units jsonb, replacements uuid[], generated jsonb
) returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform 1 from public.artworks where id = target_artwork for update;
  if not found then raise sqlstate 'PT404'; end if;
  perform 1 from public.content_units where artwork_id = target_artwork for share;
  perform 1 from public.followup_questions where artwork_id = target_artwork for update;
  if exists (
      select 1 from (select id, updated_at from public.followup_questions where artwork_id = target_artwork) q
      full join jsonb_each_text(expected_pool) snapshot on q.id = snapshot.key::uuid
      where q.updated_at is distinct from snapshot.value::timestamptz
    )
    or (select coalesce(jsonb_object_agg(id, jsonb_build_array(category, content)), '{}'::jsonb)
        from public.content_units where artwork_id = target_artwork and status in ('reviewed', 'published')) <> expected_units then
    raise sqlstate 'PT409' using message = 'Pool or evidence changed.';
  end if;
  delete from public.followup_questions where artwork_id = target_artwork and id = any(replacements);
  update public.followup_questions q set answers_by_how = item.answers_by_how, review_status = 'pending'
  from jsonb_to_recordset(generated) as item(id uuid, answers_by_how jsonb)
  where q.id = item.id and q.artwork_id = target_artwork;
  insert into public.followup_questions (artwork_id, question, category, related_unit_ids, priority, answers_by_how)
  select target_artwork, item.question, item.category, item.related_unit_ids, item.priority, item.answers_by_how
  from jsonb_to_recordset(generated) as item(
    id uuid, question text, category text, related_unit_ids uuid[], priority integer, answers_by_how jsonb
  ) where item.id is null;
end;
$$;
revoke all on function public.store_followup_generation(uuid, jsonb, jsonb, uuid[], jsonb) from public;
grant execute on function public.store_followup_generation(uuid, jsonb, jsonb, uuid[], jsonb) to authenticated;

create function public.review_followup_questions(target_artwork uuid, expected_rows jsonb, next_status text)
returns void language plpgsql security invoker set search_path = '' as $$
declare
  changed integer;
begin
  if next_status not in ('pending', 'reviewed', 'published') then raise sqlstate 'PT422'; end if;
  update public.followup_questions q set review_status = next_status
  from jsonb_each_text(expected_rows) item
  where q.id = item.key::uuid and q.artwork_id = target_artwork and q.updated_at = item.value::timestamptz
    and q.review_status <> next_status;
  get diagnostics changed = row_count;
  if changed <> (select count(*) from jsonb_each(expected_rows)) then
    raise sqlstate 'PT409' using message = 'Questions changed.';
  end if;
end;
$$;
revoke all on function public.review_followup_questions(uuid, jsonb, text) from public;
grant execute on function public.review_followup_questions(uuid, jsonb, text) to authenticated;

alter table public.admin_ai_prompt_versions drop constraint admin_ai_prompt_versions_kind_check;
alter table public.admin_ai_prompt_versions add constraint admin_ai_prompt_versions_kind_check
  check (kind in ('extraction', 'classification', 'followup'));
insert into public.admin_ai_prompt_versions(kind, version, body) values ('followup', 1,
  '작품에 특화된 자연스러운 한국어 관람객 질문을 작성하세요. 퀴즈와 일반적인 질문을 피하고, 서로 다른 근거를 활용한 질문을 우선하세요. 각 질문에 연결된 Unit만 사용해 쉬운 답변과 심화 답변을 모두 작성하세요.');
insert into public.admin_ai_active_prompts(kind, version) values ('followup', 1);

commit;
