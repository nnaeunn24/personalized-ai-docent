begin;

grant insert (kind, version) on public.admin_ai_active_prompts to authenticated;

create or replace function public.activate_missing_extraction_prompt(prompt_kind text, requested_version integer)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  selected_body text;
begin
  if prompt_kind is null or prompt_kind not in ('extraction', 'classification') then
    raise sqlstate 'PT422' using message = 'Unsupported prompt kind.';
  end if;

  perform pg_advisory_xact_lock(hashtext('docent:activate-missing-prompt'), hashtext(prompt_kind));
  if exists (select 1 from public.admin_ai_active_prompts where kind = prompt_kind) then
    raise sqlstate 'PT409' using message = 'An active version already exists.';
  end if;

  if requested_version is null then
    if exists (select 1 from public.admin_ai_prompt_versions where kind = prompt_kind) then
      raise sqlstate 'PT409' using message = 'Select an existing prompt version.';
    end if;

    -- These are the project defaults from 05_admin_ai_settings.sql.
    selected_body := case prompt_kind when 'extraction' then $extraction$
작품 설명을 개인화된 도슨트에서 독립적으로 선택할 수 있는 의미 단위로 나눈다.
원문에 명시된 핵심 정보를 빠짐없이 담되 의미가 중복되는 Unit을 만들지 않는다. 독립적인 정보는 나누되 하나의 핵심 정보를 설명하는 원인, 결과, 근거는 함께 유지한다.
원문과 동일한 언어로 작성하고 대명사 등은 다른 Unit 없이도 이해할 수 있도록 원문에 있는 대상으로 명확하게 표현한다. 원문에 없는 사실과 해석은 추가하지 않는다. 카테고리별 개수를 맞추기 위해 나누지 않는다.
각 Unit마다 내용을 직접 뒷받침하는 원문 구절을 그대로 인용한다. 원문의 순서를 가급적 유지한다.
$extraction$
      else $classification$
단어가 아니라 각 Unit이 전달하는 핵심 정보를 기준으로 하나의 주요 WHAT 카테고리를 선택한다.
VISUAL: 색채, 형태, 구도, 명암, 질감, 묘사된 대상, 관찰 가능한 시각적 효과.
MEANING: 주제, 상징, 서사, 해석, 메시지, 작가의 표현 의도, 감정적 의미.
TECHNIQUE: 재료, 도구, 제작 기법 및 과정. 제작 방법이 시각적 결과의 원인으로 설명되면 TECHNIQUE를 우선 검토한다.
BACKGROUND: 작가의 생애와 활동, 제작 배경, 역사·미술사적 맥락, 작가의 작품 세계, 소장 이력.
서로 독립적으로 선택할 수 있는 정보가 섞여 있으면 needs_split을 표시한다. 핵심 정보의 카테고리 판단이 모호하면 needs_review를 표시한다. 둘 다 해당할 수 있다. 어느 경우든 가장 적절한 카테고리 하나와 짧은 판단 근거를 작성한다.
$classification$ end;
    requested_version := 1;
    insert into public.admin_ai_prompt_versions(kind, version, body)
      values (prompt_kind, requested_version, selected_body)
      on conflict (kind, version) do nothing;
    if not found then
      raise sqlstate 'PT409' using message = 'A prompt version already exists.';
    end if;
  else
    select body into selected_body from public.admin_ai_prompt_versions
    where kind = prompt_kind and version = requested_version;
    if not found then
      raise sqlstate 'PT422' using message = 'The requested prompt version does not exist.';
    end if;
  end if;

  insert into public.admin_ai_active_prompts(kind, version)
  values (prompt_kind, requested_version)
  on conflict (kind) do nothing;
  if not found then
    raise sqlstate 'PT409' using message = 'An active version already exists.';
  end if;
  return jsonb_build_object('version', requested_version, 'body', selected_body);
end;
$$;

revoke all on function public.activate_missing_extraction_prompt(text, integer) from public, anon;
grant execute on function public.activate_missing_extraction_prompt(text, integer) to authenticated;
notify pgrst, 'reload schema';

commit;
