begin;

alter table public.exhibitions
  add column if not exists artwork_order uuid[] not null default '{}';

create or replace function public.set_exhibition_artwork_order(
  exhibition_id uuid, expected_ids uuid[], artwork_ids uuid[]
)
returns boolean
language plpgsql security invoker set search_path = '' as $$
declare
  saved_order uuid[];
  current_ids uuid[];
begin
  select e.artwork_order into saved_order
  from public.exhibitions e where e.id = $1
  for update;
  if not found then
    return false;
  end if;

  select coalesce(array_agg(a.id order by
    array_position(saved_order, a.id) nulls last, a.created_at, a.id), '{}')
  into current_ids
  from public.artworks a where a.exhibition_id = $1;

  if current_ids is distinct from expected_ids
    or artwork_ids is null
    or cardinality(current_ids) <> cardinality(artwork_ids)
    or not (current_ids <@ artwork_ids and artwork_ids <@ current_ids) then
    return false;
  end if;

  update public.exhibitions e set artwork_order = artwork_ids where e.id = $1;
  return found;
end;
$$;

revoke all on function public.set_exhibition_artwork_order(uuid, uuid[], uuid[])
  from public, anon, authenticated;
grant execute on function public.set_exhibition_artwork_order(uuid, uuid[], uuid[])
  to authenticated;

create or replace function public.visitor_exhibition(exhibition_id uuid)
returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'id', e.id, 'name', e.name, 'description', e.description, 'image_object_key', e.cover_object_key,
    'artworks', coalesce((
      select jsonb_agg(jsonb_build_object('id', a.id, 'name', a.name, 'artist', a.artist,
        'year', a.year, 'image_object_key', a.image_object_key)
        order by array_position(e.artwork_order, a.id) nulls last, a.created_at, a.id)
      from public.artworks a
      where a.exhibition_id = e.id
    ), '[]'::jsonb)
  )
  from public.exhibitions e
  where e.id = $1 and e.is_public;
$$;

notify pgrst, 'reload schema';
commit;
