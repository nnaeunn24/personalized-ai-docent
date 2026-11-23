begin;

-- Old extraction records are intentionally left unverified until retried.
alter table public.artwork_unit_extractions add column result_unit_ids uuid[];
grant update (result_unit_ids) on public.artwork_unit_extractions to authenticated;
create function public.store_verified_artwork_unit_extraction(
  target_artwork uuid, expected_description text, extracted_units jsonb,
  extractor text, classifier text
) returns jsonb
language plpgsql security invoker set search_path = ''
as $$
declare
  saved_description text;
  revision_hash text;
  inserted_count integer;
  verified_ids uuid[];
begin
  select description into saved_description
    from public.artworks where id = target_artwork for update;
  if not found or saved_description is distinct from expected_description then
    raise sqlstate 'PT409' using message = 'Artwork description changed or the artwork was removed.';
  end if;

  revision_hash := encode(sha256(convert_to(saved_description, 'UTF8')), 'hex');
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

  -- Keep the first category for repeated normalized text and honor source order.
  with candidates as (
    select item->>'content' as content, item->>'category' as category, position,
           lower(btrim(regexp_replace(item->>'content', '[[:space:]]+', ' ', 'g'))) as normalized
      from jsonb_array_elements(extracted_units) with ordinality as input(item, position)
  ), unique_units as (
    select distinct on (normalized) content, category, position, normalized
      from candidates order by normalized, position
  )
  insert into public.content_units (
    artwork_id, content, category, extraction_method, extraction_model,
    classification_method, classification_model
  )
  select target_artwork, incoming.content, incoming.category, 'automatic', extractor, 'automatic', classifier
    from unique_units incoming
    where not exists (
      select 1 from public.content_units existing
      where existing.artwork_id = target_artwork
      and lower(btrim(regexp_replace(existing.content, '[[:space:]]+', ' ', 'g'))) = incoming.normalized
    )
    order by incoming.position;
  get diagnostics inserted_count = row_count;
  select array_agg(u.id order by u.number) into verified_ids
    from public.content_units u
    where u.artwork_id = target_artwork and exists (
      select 1 from jsonb_array_elements(extracted_units) incoming
      where lower(btrim(regexp_replace(u.content, '[[:space:]]+', ' ', 'g')))
        = lower(btrim(regexp_replace(incoming->>'content', '[[:space:]]+', ' ', 'g')))
    );
  if coalesce(cardinality(verified_ids), 0) = 0 then
    raise sqlstate 'PT422' using message = 'No stored units match the extraction.';
  end if;

  insert into public.artwork_unit_extractions (artwork_id, source_hash, result_unit_ids)
    values (target_artwork, revision_hash, verified_ids)
    on conflict (artwork_id, source_hash) do update set result_unit_ids = excluded.result_unit_ids;
  return jsonb_build_object('inserted_count', inserted_count, 'unit_ids', verified_ids);
end;
$$;

revoke all on function public.store_verified_artwork_unit_extraction(uuid, text, jsonb, text, text) from public, anon;
grant execute on function public.store_verified_artwork_unit_extraction(uuid, text, jsonb, text, text) to authenticated;
notify pgrst, 'reload schema';

commit;
