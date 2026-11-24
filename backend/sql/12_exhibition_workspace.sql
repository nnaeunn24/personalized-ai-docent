begin;

alter table public.content_units
  add column if not exists is_required boolean not null default false;

create or replace function public.visitor_exhibitions()
returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', e.id, 'name', e.name, 'code', e.code, 'description', e.description,
    'image_object_key', e.cover_object_key
  ) order by e.created_at desc, e.id), '[]'::jsonb)
  from public.exhibitions e
  where e.is_public;
$$;

create or replace function public.transition_workspace_unit(
  target_id uuid, expected_at timestamptz, next_status text, edits jsonb
) returns public.content_units
language plpgsql security invoker set search_path = '' as $$
declare
  unit public.content_units;
begin
  select * into unit from public.content_units
  where id = target_id and updated_at = expected_at for update;
  if not found then
    raise sqlstate 'PT409' using message = 'Unit이 변경되었습니다. 목록을 새로고침해 주세요.';
  end if;
  if next_status not in ('unpublish', 'reviewed', 'published') then
    raise sqlstate 'PT422' using message = '지원하지 않는 Unit 상태입니다.';
  end if;
  if edits is not null then
    update public.content_units set
      content = edits->>'content',
      category = edits->>'category',
      is_required = coalesce((edits->>'is_required')::boolean, unit.is_required)
    where id = target_id returning * into unit;
  end if;
  if next_status = 'unpublish' and unit.status = 'published' then
    update public.content_units set status = 'reviewed' where id = target_id returning * into unit;
  elsif next_status in ('reviewed', 'published') and unit.status = 'pending' then
    update public.content_units set status = 'reviewed' where id = target_id returning * into unit;
  end if;
  if next_status = 'published' and unit.status = 'reviewed' then
    update public.content_units set status = 'published' where id = target_id returning * into unit;
  end if;
  return unit;
end;
$$;

-- Keep the current classification provenance and review rules, and allow unpublishing.
create or replace function public.admin_unit_status_guard()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.status := 'pending';
    return new;
  end if;
  if new.category is distinct from old.category then
    new.classification_method := 'manual';
    new.classification_model := null;
  end if;
  if (new.content, new.category) is distinct from (old.content, old.category) then
    new.status := 'pending';
  elsif new.status is distinct from old.status
      and not ((old.status = 'pending' and new.status = 'reviewed')
            or (old.status = 'reviewed' and new.status = 'published')
            or (old.status = 'published' and new.status = 'reviewed')) then
    raise exception 'Invalid Unit status transition: % -> %', old.status, new.status
      using errcode = '23514';
  end if;
  return new;
end;
$$;

create or replace function public.publish_workspace_followup(
  target_artwork uuid, target_id uuid, expected_at timestamptz, edits jsonb
) returns public.followup_questions
language plpgsql security invoker set search_path = '' as $$
declare
  item public.followup_questions;
begin
  perform 1 from public.content_units where artwork_id = target_artwork order by id for share;
  select * into item from public.followup_questions
  where id = target_id and artwork_id = target_artwork and updated_at = expected_at for update;
  if not found then
    raise sqlstate 'PT409' using message = '질문이 변경되었습니다. 목록을 새로고침해 주세요.';
  end if;
  if edits is not null then
    update public.followup_questions set
      question = edits->>'question',
      category = edits->>'category',
      priority = (edits->>'priority')::integer,
      answers_by_how = edits->'answers_by_how',
      related_unit_ids = array(select value::uuid from jsonb_array_elements_text(edits->'related_unit_ids'))
    where id = target_id returning * into item;
  end if;
  if coalesce(length(btrim(item.answers_by_how->>'Basic')), 0) = 0
      or coalesce(length(btrim(item.answers_by_how->>'Advanced')), 0) = 0 then
    raise sqlstate 'PT422' using message = 'Basic 및 Advanced 답변이 모두 필요합니다.';
  end if;
  if not public.followup_evidence_valid(target_artwork, item.related_unit_ids, true) then
    raise sqlstate 'PT422' using message = '연결된 Content Unit을 모두 게시해야 합니다.';
  end if;
  if item.review_status = 'pending' then
    update public.followup_questions set review_status = 'reviewed'
    where id = target_id returning * into item;
  end if;
  if item.review_status = 'reviewed' then
    update public.followup_questions set review_status = 'published'
    where id = target_id returning * into item;
  end if;
  return item;
end;
$$;

create or replace function public.followup_recheck_after_unit_change()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'DELETE' or (old.content, old.category, old.artwork_id)
      is distinct from (new.content, new.category, new.artwork_id)
      or (old.status <> 'pending' and new.status = 'pending') then
    update public.followup_questions
    set review_status = 'pending', needs_recheck = true
    where related_unit_ids @> array[old.id] and artwork_id = old.artwork_id;
  elsif old.status = 'published' and new.status = 'reviewed' then
    update public.followup_questions
    set review_status = 'pending', needs_recheck = true
    where related_unit_ids @> array[old.id] and artwork_id = old.artwork_id and review_status = 'published';
  end if;
  return null;
end;
$$;

revoke all on function public.transition_workspace_unit(uuid, timestamptz, text, jsonb),
  public.publish_workspace_followup(uuid, uuid, timestamptz, jsonb) from public, anon;
grant execute on function public.transition_workspace_unit(uuid, timestamptz, text, jsonb),
  public.publish_workspace_followup(uuid, uuid, timestamptz, jsonb) to authenticated;

commit;
