-- Destructive reset of the six allowlisted legacy tables. Review and back up first.
begin;
set local lock_timeout = '5s';

-- Legacy drop section for 02_reset_schema.sql.
do $drop_legacy$
declare
  -- Earlier entries are preferred when there is no FK ordering constraint.
  target_names text[] := array[
    'content_units', 'exhibition_artworks', 'artworks',
    'exhibitions', 'assets', 'alembic_version'
  ];
  remaining oid[] := array[]::oid[];
  target_name text;
  target_oid oid;
  inheritance_link text;
begin
  foreach target_name in array target_names loop
    target_oid := to_regclass(format('public.%I', target_name));
    if target_oid is not null then
      execute format('lock table only public.%I in access exclusive mode', target_name);
      remaining := array_append(remaining, target_oid);
    end if;
  end loop;

  -- Inheritance and partition links need a separate migration decision.
  select format('%s -> %s', inhrelid::regclass, inhparent::regclass)
    into inheritance_link
    from pg_catalog.pg_inherits
    where inhrelid = any(remaining) or inhparent = any(remaining)
    limit 1;
  if found then
    raise exception 'Legacy reset stopped: inheritance or partition dependency: %', inheritance_link;
  end if;

  while cardinality(remaining) > 0 loop
    select candidate.relation_id into target_oid
    from unnest(remaining) with ordinality as candidate(relation_id, position)
    where not exists (
      select 1
      from pg_catalog.pg_constraint fk
      where fk.contype = 'f'
        and fk.confrelid = candidate.relation_id
        and fk.conrelid <> fk.confrelid
        and fk.conrelid = any(remaining)
    )
    order by candidate.position
    limit 1;

    if not found then
      raise exception 'Legacy reset stopped: circular foreign keys among %', remaining::regclass[];
    end if;

    -- PostgreSQL reports external dependencies and aborts the transaction.
    execute format('drop table %s restrict', target_oid::regclass);
    remaining := array_remove(remaining, target_oid);
  end loop;
end;
$drop_legacy$;

-- Schema creation section for 02_reset_schema.sql.
create table public.admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(btrim(display_name)) between 1 and 120),
  created_at timestamptz not null default now()
);

create table public.exhibitions (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(btrim(name)) between 1 and 200),
  description text not null default '' check (char_length(description) <= 20000),
  cover_object_key text,
  code text not null unique default replace(gen_random_uuid()::text, '-', ''),
  is_public boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.artworks (
  id uuid primary key default gen_random_uuid(),
  exhibition_id uuid not null references public.exhibitions(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 200),
  artist text not null default '' check (char_length(artist) <= 200),
  external_id text not null default '' check (char_length(external_id) <= 200),
  description text not null default '' check (char_length(description) <= 100000),
  source_url text not null default '' check (char_length(source_url) <= 2048),
  language text not null default '' check (language in ('', 'ko', 'en', 'other')),
  year text not null default '' check (char_length(year) <= 100),
  image_object_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.content_units (
  id uuid primary key default gen_random_uuid(),
  artwork_id uuid not null references public.artworks(id) on delete cascade,
  number bigint generated always as identity unique,
  content text not null check (char_length(btrim(content)) between 1 and 20000),
  category text not null check (category in ('VISUAL', 'MEANING', 'TECHNIQUE', 'BACKGROUND')),
  status text not null default 'pending' check (status in ('pending', 'reviewed', 'published')),
  extraction_method text not null default 'manual',
  extraction_model text,
  classification_method text not null default 'manual',
  classification_model text,
  constraint content_units_extraction_provenance check (
    (extraction_method = 'manual' and extraction_model is null)
    or (extraction_method = 'automatic' and extraction_model is not null
        and char_length(btrim(extraction_model)) between 1 and 200)
  ),
  constraint content_units_classification_provenance check (
    (classification_method = 'manual' and classification_model is null)
    or (classification_method = 'automatic' and classification_model is not null
        and char_length(btrim(classification_model)) between 1 and 200)
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index artworks_exhibition_id_idx on public.artworks (exhibition_id);
create index content_units_artwork_status_idx on public.content_units (artwork_id, status);

create function public.admin_touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create function public.admin_unit_status_guard()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.status := 'pending';
    return new;
  end if;

  if new.category is distinct from old.category then
    -- The current update path is a curator edit.
    new.classification_method := 'manual';
    new.classification_model := null;
  end if;

  if (new.content, new.category) is distinct from (old.content, old.category) then
    new.status := 'pending';
  elsif new.status is distinct from old.status
      and not ((old.status = 'pending' and new.status = 'reviewed')
            or (old.status = 'reviewed' and new.status = 'published')) then
    raise exception 'Invalid Unit status transition: % -> %', old.status, new.status
      using errcode = '23514';
  end if;
  return new;
end;
$$;

create trigger exhibitions_touch before update on public.exhibitions
for each row execute function public.admin_touch_updated_at();
create trigger artworks_touch before update on public.artworks
for each row execute function public.admin_touch_updated_at();
create trigger content_units_touch before update on public.content_units
for each row execute function public.admin_touch_updated_at();
create trigger content_units_status_guard before insert or update on public.content_units
for each row execute function public.admin_unit_status_guard();

alter table public.admin_users enable row level security;
alter table public.exhibitions enable row level security;
alter table public.artworks enable row level security;
alter table public.content_units enable row level security;

revoke all on public.admin_users, public.exhibitions, public.artworks, public.content_units
  from public, anon, authenticated;
grant select on public.admin_users to authenticated;
grant select, insert, update, delete on public.exhibitions, public.artworks, public.content_units to authenticated;

create policy admin_read_self on public.admin_users for select to authenticated
  using (user_id = (select auth.uid()) and coalesce((select auth.jwt()) ->> 'is_anonymous', 'false') <> 'true');

create policy exhibitions_admin on public.exhibitions for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));
create policy artworks_admin on public.artworks for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));
create policy content_units_admin on public.content_units for all to authenticated
  using (exists (select 1 from public.admin_users where user_id = (select auth.uid())))
  with check (exists (select 1 from public.admin_users where user_id = (select auth.uid())));

commit;
