begin;

create table public.artwork_unit_extractions (
  artwork_id uuid not null references public.artworks(id) on delete cascade,
  source_hash text not null,
  created_at timestamptz not null default now(),
  primary key (artwork_id, source_hash)
);

alter table public.artwork_unit_extractions enable row level security;
revoke all on public.artwork_unit_extractions from public, anon, authenticated;
grant select, insert on public.artwork_unit_extractions to authenticated;
create policy artwork_unit_extractions_admin on public.artwork_unit_extractions
  for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));

create function public.store_artwork_unit_extraction(
  target_artwork uuid, expected_description text, extracted_units jsonb,
  extractor text, classifier text
) returns integer
language plpgsql security invoker set search_path = ''
as $$
declare
  saved_description text;
  revision_hash text;
  inserted_count integer;
begin
  select description into saved_description
    from public.artworks where id = target_artwork for update;
  if not found or saved_description is distinct from expected_description then
    raise sqlstate 'PT409' using message = 'Artwork description changed or the artwork was removed.';
  end if;

  revision_hash := encode(sha256(convert_to(saved_description, 'UTF8')), 'hex');
  insert into public.artwork_unit_extractions (artwork_id, source_hash)
    values (target_artwork, revision_hash) on conflict do nothing;
  if not found then
    return 0;
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
  return inserted_count;
end;
$$;

revoke all on function public.store_artwork_unit_extraction(uuid, text, jsonb, text, text) from public, anon;
grant execute on function public.store_artwork_unit_extraction(uuid, text, jsonb, text, text) to authenticated;
notify pgrst, 'reload schema';

commit;
