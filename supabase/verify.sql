-- GRIDOPT - post-migration security and integrity checks.
--
-- Run this in the Supabase SQL editor after schema.sql and seed.sql. It reads
-- only catalog tables and the two seeded tables; it changes nothing.
--
-- The DO block at the end raises on the first violation, so a clean run means
-- every assertion below held. The SELECTs above it are there to be read.

-- --------------------------------------------------------------------------
-- 1. Row counts against the CSV.
-- --------------------------------------------------------------------------
select 'stations'           as table_name, count(*) as rows, 26 as expected from public.stations
union all
select 'transmission_lines' as table_name, count(*) as rows, 38 as expected from public.transmission_lines;

-- --------------------------------------------------------------------------
-- 2. No station stored twice, no line stored twice in either direction.
-- --------------------------------------------------------------------------
select 'duplicate station names' as check_name, count(*) as violations
from (select name from public.stations group by name having count(*) > 1) x
union all
select 'duplicate line pairs', count(*)
from (
  select least(source_id, destination_id) a, greatest(source_id, destination_id) b
  from public.transmission_lines
  group by 1, 2 having count(*) > 1
) y
union all
select 'lines with an unknown endpoint', count(*)
from public.transmission_lines l
where not exists (select 1 from public.stations s where s.id = l.source_id)
   or not exists (select 1 from public.stations d where d.id = l.destination_id);

-- --------------------------------------------------------------------------
-- 3. RLS is enabled AND forced on every table in public.
-- --------------------------------------------------------------------------
select
  c.relname            as table_name,
  c.relrowsecurity     as rls_enabled,
  c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

-- --------------------------------------------------------------------------
-- 4. Grants held by the Data API roles. Expected: no rows at all.
--    RLS is not sufficient on its own - a grant is what makes a table
--    reachable through PostgREST in the first place.
-- --------------------------------------------------------------------------
select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('anon', 'authenticated', 'PUBLIC')
order by grantee, table_name, privilege_type;

-- --------------------------------------------------------------------------
-- 5. The policies that are actually in force.
-- --------------------------------------------------------------------------
select schemaname, tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- --------------------------------------------------------------------------
-- 6. The view must run as the invoker, or it would leak past RLS.
-- --------------------------------------------------------------------------
select
  c.relname as view_name,
  coalesce(
    (select option_value from pg_options_to_table(c.reloptions)
      where option_name = 'security_invoker'),
    'false'
  ) as security_invoker
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'v';

-- --------------------------------------------------------------------------
-- Assertions. Raises on the first failure; silence means everything passed.
-- --------------------------------------------------------------------------
do $$
declare
  n int;
  bad text;
begin
  select count(*) into n from public.stations;
  if n <> 26 then raise exception 'stations: expected 26 rows, found %', n; end if;

  select count(*) into n from public.transmission_lines;
  if n <> 38 then raise exception 'transmission_lines: expected 38 rows, found %', n; end if;

  -- Every table in public must have RLS enabled and forced.
  select string_agg(c.relname, ', ') into bad
  from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
  where ns.nspname = 'public' and c.relkind = 'r'
    and (c.relrowsecurity = false or c.relforcerowsecurity = false);
  if bad is not null then
    raise exception 'RLS not enabled+forced on: %', bad;
  end if;

  -- The Data API roles must hold no privileges on anything in public.
  select string_agg(distinct grantee || ':' || table_name, ', ') into bad
  from information_schema.role_table_grants
  where table_schema = 'public' and grantee in ('anon', 'authenticated', 'PUBLIC');
  if bad is not null then
    raise exception 'Data API roles still hold grants: %', bad;
  end if;

  -- The join view must be security_invoker, or it bypasses the policies above.
  select string_agg(c.relname, ', ') into bad
  from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
  where ns.nspname = 'public' and c.relkind = 'v'
    and coalesce((select option_value from pg_options_to_table(c.reloptions)
                   where option_name = 'security_invoker'), 'false') <> 'true';
  if bad is not null then
    raise exception 'view(s) not security_invoker: %', bad;
  end if;

  raise notice 'All checks passed: 26 stations, 38 lines, RLS enabled+forced, no Data API grants.';
end $$;
