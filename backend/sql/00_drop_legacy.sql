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
