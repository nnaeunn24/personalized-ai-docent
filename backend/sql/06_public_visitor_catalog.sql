begin;

-- Narrow public projections. Existing table grants and administrator policies stay in place.
create function public.visitor_exhibitions()
returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', e.id, 'name', e.name, 'code', e.code)
    order by e.created_at desc, e.id), '[]'::jsonb)
  from public.exhibitions e
  where e.is_public;
$$;

create function public.visitor_exhibition(exhibition_id uuid)
returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'id', e.id, 'name', e.name, 'description', e.description,
    'artworks', coalesce((
      select jsonb_agg(jsonb_build_object('id', a.id, 'name', a.name, 'artist', a.artist, 'year', a.year)
        order by a.created_at, a.id)
      from public.artworks a
      where a.exhibition_id = e.id
    ), '[]'::jsonb)
  )
  from public.exhibitions e
  where e.id = $1 and e.is_public;
$$;

create function public.visitor_artwork(exhibition_id uuid, artwork_id uuid)
returns jsonb
language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'id', a.id, 'name', a.name, 'artist', a.artist, 'year', a.year,
    'exhibition', jsonb_build_object('id', e.id, 'name', e.name),
    'units', coalesce((
      select jsonb_agg(jsonb_build_object('id', u.id, 'content', u.content, 'category', u.category)
        order by u.number)
      from public.content_units u
      where u.artwork_id = a.id and u.status = 'published'
    ), '[]'::jsonb)
  )
  from public.artworks a
  join public.exhibitions e on e.id = a.exhibition_id
  where e.id = $1 and a.id = $2 and e.is_public;
$$;

revoke all on function public.visitor_exhibitions(), public.visitor_exhibition(uuid),
  public.visitor_artwork(uuid, uuid) from public, anon, authenticated;
grant execute on function public.visitor_exhibitions(), public.visitor_exhibition(uuid),
  public.visitor_artwork(uuid, uuid) to anon, authenticated;
notify pgrst, 'reload schema';

commit;
