begin;

create table public.admin_ai_prompt_versions (
  kind text not null check (kind in ('extraction', 'classification')),
  version integer not null check (version > 0),
  body text not null check (char_length(btrim(body)) between 1 and 12000),
  created_at timestamptz not null default now(),
  primary key (kind, version)
);

create table public.admin_ai_active_prompts (
  kind text primary key,
  version integer not null,
  constraint admin_ai_active_version_fkey foreign key (kind, version)
    references public.admin_ai_prompt_versions (kind, version)
);

create table public.admin_ai_runs (
  id uuid primary key default gen_random_uuid(),
  artwork_id uuid references public.artworks(id) on delete set null,
  mode text not null check (mode in ('test', 'artwork')),
  description text not null,
  extraction_prompt_version integer,
  classification_prompt_version integer,
  extraction_prompt text not null,
  classification_prompt text not null,
  extraction_model text not null,
  classification_model text not null,
  extraction_result jsonb not null,
  classification_result jsonb not null,
  created_at timestamptz not null default now()
);
create index admin_ai_runs_mode_created_idx on public.admin_ai_runs (mode, created_at desc);

alter table public.artwork_unit_extractions add column ai_run_id uuid references public.admin_ai_runs(id);
grant update (ai_run_id) on public.artwork_unit_extractions to authenticated;

alter table public.content_units
  add column ai_run_id uuid references public.admin_ai_runs(id),
  add column source_evidence jsonb not null default '[]'::jsonb,
  add column classification_rationale text,
  add column needs_split boolean not null default false,
  add column needs_review boolean not null default false;

alter table public.admin_ai_prompt_versions enable row level security;
alter table public.admin_ai_active_prompts enable row level security;
alter table public.admin_ai_runs enable row level security;
revoke all on public.admin_ai_prompt_versions, public.admin_ai_active_prompts, public.admin_ai_runs from public, anon, authenticated;
grant select, insert on public.admin_ai_prompt_versions, public.admin_ai_runs to authenticated;
grant select, update (version) on public.admin_ai_active_prompts to authenticated;

create policy ai_prompt_versions_admin on public.admin_ai_prompt_versions for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));
create policy ai_active_prompts_admin on public.admin_ai_active_prompts for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));
create policy ai_runs_admin on public.admin_ai_runs for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));

insert into public.admin_ai_prompt_versions(kind, version, body) values
('extraction', 1, $extraction$
작품 설명을 개인화된 도슨트에서 독립적으로 선택할 수 있는 의미 단위로 나눈다.
원문에 명시된 핵심 정보를 빠짐없이 담되 의미가 중복되는 Unit을 만들지 않는다. 독립적인 정보는 나누되 하나의 핵심 정보를 설명하는 원인, 결과, 근거는 함께 유지한다.
원문과 동일한 언어로 작성하고 대명사 등은 다른 Unit 없이도 이해할 수 있도록 원문에 있는 대상으로 명확하게 표현한다. 원문에 없는 사실과 해석은 추가하지 않는다. 카테고리별 개수를 맞추기 위해 나누지 않는다.
각 Unit마다 내용을 직접 뒷받침하는 원문 구절을 그대로 인용한다. 원문의 순서를 가급적 유지한다.
$extraction$),
('classification', 1, $classification$
단어가 아니라 각 Unit이 전달하는 핵심 정보를 기준으로 하나의 주요 WHAT 카테고리를 선택한다.
VISUAL: 색채, 형태, 구도, 명암, 질감, 묘사된 대상, 관찰 가능한 시각적 효과.
MEANING: 주제, 상징, 서사, 해석, 메시지, 작가의 표현 의도, 감정적 의미.
TECHNIQUE: 재료, 도구, 제작 기법 및 과정. 제작 방법이 시각적 결과의 원인으로 설명되면 TECHNIQUE를 우선 검토한다.
BACKGROUND: 작가의 생애와 활동, 제작 배경, 역사·미술사적 맥락, 작가의 작품 세계, 소장 이력.
서로 독립적으로 선택할 수 있는 정보가 섞여 있으면 needs_split을 표시한다. 핵심 정보의 카테고리 판단이 모호하면 needs_review를 표시한다. 둘 다 해당할 수 있다. 어느 경우든 가장 적절한 카테고리 하나와 짧은 판단 근거를 작성한다.
$classification$);

insert into public.admin_ai_active_prompts(kind, version)
select kind, version from public.admin_ai_prompt_versions;

create function public.set_admin_ai_prompt(
  prompt_kind text, expected_version integer, new_body text, restore_version integer
) returns integer language plpgsql security invoker set search_path = '' as $$
declare
  current_version integer;
  next_version integer;
begin
  select version into current_version
  from public.admin_ai_active_prompts where kind = prompt_kind for update;
  if not found then
    raise sqlstate 'PT404' using message = 'Prompt not found.';
  end if;
  if current_version is distinct from expected_version then
    raise sqlstate 'PT409' using message = 'Active prompt changed.';
  end if;
  if restore_version is null then
    select max(version) + 1 into next_version
    from public.admin_ai_prompt_versions where kind = prompt_kind;
    insert into public.admin_ai_prompt_versions(kind, version, body)
      values (prompt_kind, next_version, new_body);
  else
    next_version := restore_version;
  end if;
  update public.admin_ai_active_prompts set version = next_version where kind = prompt_kind;
  return next_version;
end;
$$;

revoke all on function public.set_admin_ai_prompt(text, integer, text, integer) from public, anon;
grant execute on function public.set_admin_ai_prompt(text, integer, text, integer) to authenticated;

create function public.store_prompted_artwork_extraction(
  target_artwork uuid, expected_description text, revision_hash text,
  run_data jsonb, extracted_units jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  saved_description text;
  inserted_count integer;
  verified_ids uuid[];
  saved_run_id uuid;
begin
  select description into saved_description from public.artworks where id = target_artwork for update;
  if not found or saved_description is distinct from expected_description then
    raise sqlstate 'PT409' using message = 'Artwork description changed or the artwork was removed.';
  end if;

  select array_agg(u.id order by u.number) into verified_ids
  from public.artwork_unit_extractions e
  join public.content_units u on u.artwork_id = e.artwork_id and u.id = any(e.result_unit_ids)
  where e.artwork_id = target_artwork and e.source_hash = revision_hash;
  if cardinality(verified_ids) > 0 then
    return jsonb_build_object('inserted_count', 0, 'unit_ids', verified_ids);
  end if;
  if jsonb_typeof(extracted_units) is distinct from 'array'
     or jsonb_array_length(extracted_units) not between 1 and 80 then
    raise sqlstate 'PT422' using message = 'Invalid extraction batch.';
  end if;

  insert into public.admin_ai_runs (
    artwork_id, mode, description, extraction_prompt_version, classification_prompt_version,
    extraction_prompt, classification_prompt, extraction_model, classification_model,
    extraction_result, classification_result
  ) values (
    target_artwork, 'artwork', saved_description, (run_data->>'extraction_prompt_version')::integer,
    (run_data->>'classification_prompt_version')::integer, run_data->>'extraction_prompt',
    run_data->>'classification_prompt', run_data->>'extraction_model', run_data->>'classification_model',
    run_data->'extraction_result', run_data->'classification_result'
  ) returning id into saved_run_id;

  with candidates as (
    select item, position, lower(btrim(regexp_replace(item->>'content', '[[:space:]]+', ' ', 'g'))) as normalized
    from jsonb_array_elements(extracted_units) with ordinality as data(item, position)
  ), unique_units as (
    select distinct on (normalized) item, position, normalized from candidates order by normalized, position
  )
  insert into public.content_units (
    artwork_id, content, category, extraction_method, extraction_model, classification_method,
    classification_model, ai_run_id, source_evidence, classification_rationale, needs_split, needs_review
  )
  select target_artwork, item->>'content', item->>'category', 'automatic', run_data->>'extraction_model',
    'automatic', run_data->>'classification_model', saved_run_id, item->'evidence', item->>'rationale',
    (item->>'needs_split')::boolean, (item->>'needs_review')::boolean
  from unique_units incoming
  where not exists (
    select 1 from public.content_units existing where existing.artwork_id = target_artwork
    and lower(btrim(regexp_replace(existing.content, '[[:space:]]+', ' ', 'g'))) = incoming.normalized
  )
  order by position;
  get diagnostics inserted_count = row_count;

  select array_agg(u.id order by u.number) into verified_ids
  from public.content_units u where u.artwork_id = target_artwork and exists (
    select 1 from jsonb_array_elements(extracted_units) incoming
    where lower(btrim(regexp_replace(u.content, '[[:space:]]+', ' ', 'g')))
      = lower(btrim(regexp_replace(incoming->>'content', '[[:space:]]+', ' ', 'g')))
  );
  if coalesce(cardinality(verified_ids), 0) = 0 then
    raise sqlstate 'PT422' using message = 'No stored units match the extraction.';
  end if;

  insert into public.artwork_unit_extractions (artwork_id, source_hash, result_unit_ids, ai_run_id)
    values (target_artwork, revision_hash, verified_ids, saved_run_id)
    on conflict (artwork_id, source_hash)
      do update set result_unit_ids = excluded.result_unit_ids, ai_run_id = excluded.ai_run_id;
  return jsonb_build_object('inserted_count', inserted_count, 'unit_ids', verified_ids);
end;
$$;

revoke all on function public.store_prompted_artwork_extraction(uuid,text,text,jsonb,jsonb) from public, anon;
grant execute on function public.store_prompted_artwork_extraction(uuid,text,text,jsonb,jsonb) to authenticated;
notify pgrst, 'reload schema';

commit;
