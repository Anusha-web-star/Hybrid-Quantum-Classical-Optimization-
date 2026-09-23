-- GRIDOPT - Supabase schema for the network dataset.
--
-- Scope: stations and transmission lines only. No authentication, no user
-- tables, no application state. The existing FastAPI login screen and every
-- solver are untouched by this file.
--
-- Source of truth remains data/transmition_lines.csv.csv. These tables are
-- seeded FROM that file (see generate_seed.py -> seed.sql); the CSV is never
-- written to, renamed, or derived from the database.
--
-- Safe to re-run: every statement is idempotent.
--
-- Run order:
--   1. schema.sql   (this file)
--   2. seed.sql     (generated from the CSV)
--   3. verify.sql   (grants + RLS assertions)

begin;

-- ---------------------------------------------------------------------------
-- stations
--
-- One row per distinct station name in the CSV. `name` is the natural key: the
-- CSV identifies stations by name and the API returns them by name, so the
-- unique constraint on it is what prevents duplicate station records.
-- ---------------------------------------------------------------------------
create table if not exists public.stations (
  id          bigint generated always as identity primary key,
  name        text        not null,
  type        text        not null,
  latitude    double precision not null,
  longitude   double precision not null,
  created_at  timestamptz not null default now(),

  constraint stations_name_key unique (name),
  constraint stations_latitude_range  check (latitude  between  -90 and  90),
  constraint stations_longitude_range check (longitude between -180 and 180)
);

comment on table  public.stations is 'Stations derived from the transmission-line CSV. Seeded, not authored.';
comment on column public.stations.name is 'Natural key. Matches the Source/Destination values in the CSV exactly.';

-- ---------------------------------------------------------------------------
-- transmission_lines
--
-- One row per CSV data row. Endpoints are foreign keys into stations rather
-- than repeated names, so a station exists exactly once no matter how many
-- lines touch it.
--
-- `csv_row` keeps provenance: it is the 1-based line number in the CSV the row
-- came from, so any value here can be traced back to the file it came from.
-- ---------------------------------------------------------------------------
create table if not exists public.transmission_lines (
  id              bigint generated always as identity primary key,
  source_id       bigint not null references public.stations (id) on delete restrict,
  destination_id  bigint not null references public.stations (id) on delete restrict,
  type            text   not null,
  distance_km     double precision not null,
  voltage_kv      double precision not null,
  capacity_mw     double precision not null,
  loss_percent    double precision not null,
  energy_loss_mw  double precision not null,
  csv_row         integer not null,
  created_at      timestamptz not null default now(),

  constraint transmission_lines_no_self_loop check (source_id <> destination_id),
  constraint transmission_lines_distance_positive check (distance_km    > 0),
  constraint transmission_lines_voltage_positive  check (voltage_kv     > 0),
  constraint transmission_lines_capacity_positive check (capacity_mw   >= 0),
  constraint transmission_lines_energy_loss_positive check (energy_loss_mw >= 0),
  constraint transmission_lines_loss_percent_range check (loss_percent between 0 and 100)
);

-- A line is undirected: A->B and B->A are the same physical circuit. Indexing
-- the *unordered* pair is what stops the same line being stored twice.
create unique index if not exists transmission_lines_pair_key
  on public.transmission_lines (
    least(source_id, destination_id),
    greatest(source_id, destination_id)
  );

create index if not exists transmission_lines_source_idx      on public.transmission_lines (source_id);
create index if not exists transmission_lines_destination_idx on public.transmission_lines (destination_id);

comment on table  public.transmission_lines is 'Transmission lines, one row per CSV data row. Undirected: the pair is unique regardless of direction.';
comment on column public.transmission_lines.csv_row is 'Provenance: 1-based line number in the source CSV.';

-- ---------------------------------------------------------------------------
-- A read-only join that speaks names, the way the API does.
--
-- security_invoker = true is essential: without it the view would run with the
-- privileges of its owner and would hand out rows that the caller's own RLS
-- policies deny. With it, the base-table policies below still apply.
-- ---------------------------------------------------------------------------
create or replace view public.transmission_lines_expanded
with (security_invoker = true) as
select
  l.id,
  s.name  as source,
  d.name  as destination,
  l.type,
  l.distance_km,
  l.voltage_kv,
  l.capacity_mw,
  l.loss_percent,
  l.energy_loss_mw,
  l.csv_row
from public.transmission_lines l
join public.stations s on s.id = l.source_id
join public.stations d on d.id = l.destination_id;

-- ===========================================================================
-- SECURITY
--
-- Two independent gates, because RLS alone is not sufficient: PostgREST can
-- only reach a table if the role has been GRANTed on it, and a policy can only
-- filter rows the grant already allows. Both are set explicitly below.
--
-- Posture: the Data API is closed. Nothing in this application reads these
-- tables from the browser - FastAPI is the only consumer, and it connects with
-- the service_role key, which bypasses RLS by design. So the least privilege
-- that the application actually requires from `anon` and `authenticated` is
-- none at all, and that is what is granted.
--
-- Opening read access later is a deliberate, reviewable change: see the
-- OPTIONAL block at the end of this file.
-- ===========================================================================

alter table public.stations            enable row level security;
alter table public.transmission_lines  enable row level security;

-- FORCE also subjects the table owner to its policies. Without it, anything
-- connecting as the owner silently skips every policy below.
alter table public.stations            force row level security;
alter table public.transmission_lines  force row level security;

-- Gate 1: grants. Remove the blanket privileges Supabase hands the API roles
-- on new objects in `public`.
revoke all on public.stations                    from anon, authenticated, public;
revoke all on public.transmission_lines          from anon, authenticated, public;
revoke all on public.transmission_lines_expanded from anon, authenticated, public;

-- The same, for anything added to this schema later. Without this, the next
-- table created here starts out reachable again.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

-- Gate 2: policies. RLS denies everything by default once enabled, so the
-- absence of a permissive policy for anon/authenticated IS the deny rule.
-- These two exist to make the intent explicit and self-documenting rather
-- than implied by omission, and to fail loudly if a grant is ever restored
-- by accident.
drop policy if exists stations_no_public_access on public.stations;
create policy stations_no_public_access
  on public.stations
  for all
  to anon, authenticated
  using (false)
  with check (false);

drop policy if exists transmission_lines_no_public_access on public.transmission_lines;
create policy transmission_lines_no_public_access
  on public.transmission_lines
  for all
  to anon, authenticated
  using (false)
  with check (false);

commit;

-- ===========================================================================
-- OPTIONAL - read-only network data over the Data API.
--
-- Apply this ONLY if the browser is ever given the publishable (anon) key and
-- has to read the network directly. It grants SELECT and nothing else: no
-- insert, update or delete, on either role. Today the application does not
-- need it, so it is left unapplied.
--
--   grant select on public.stations                    to anon, authenticated;
--   grant select on public.transmission_lines          to anon, authenticated;
--   grant select on public.transmission_lines_expanded to anon, authenticated;
--
--   drop policy if exists stations_no_public_access on public.stations;
--   create policy stations_read_only
--     on public.stations for select to anon, authenticated using (true);
--
--   drop policy if exists transmission_lines_no_public_access on public.transmission_lines;
--   create policy transmission_lines_read_only
--     on public.transmission_lines for select to anon, authenticated using (true);
--
-- Note what this would mean: the network becomes world-readable to anyone
-- holding the publishable key, which is public by definition. That is a
-- disclosure decision about the dataset, not a technical one.
-- ===========================================================================
