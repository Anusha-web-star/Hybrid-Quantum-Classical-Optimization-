"""Generate supabase/seed.sql from the transmission-line CSV.

The CSV is the source of truth. Every value in the generated file is read from
it through `phase1.data_loader` - the same loader the API and the solvers use -
so the database cannot drift from the dataset, and no value is ever typed by
hand.

This reads the CSV and writes seed.sql. It does not connect to anything, and it
never writes to the dataset.

    .venv\\Scripts\\python.exe supabase/generate_seed.py

Re-running it is safe, and so is re-running the SQL it produces: stations are
upserted on their name, lines on the unordered pair of their endpoints.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from phase1.data_loader import load_dataset  # noqa: E402

OUTPUT = PROJECT_ROOT / "supabase" / "seed.sql"


def sql_str(value: str) -> str:
    """A single-quoted SQL literal, with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def sql_num(value: float) -> str:
    """Python's float repr round-trips exactly, so the CSV value is preserved."""
    return repr(value)


def build() -> str:
    dataset = load_dataset(data_dir=str(PROJECT_ROOT / "data"))

    stations = [dataset.stations[name] for name in sorted(dataset.stations)]
    lines = sorted(dataset.connections, key=lambda c: c.row_number)

    out: list[str] = []
    add = out.append

    add("-- GRIDOPT seed data - GENERATED, do not edit by hand.")
    add(f"-- Source: {Path(dataset.path).name}")
    add(f"-- Regenerate with: .venv\\Scripts\\python.exe supabase/generate_seed.py")
    add(f"-- Contents: {len(stations)} stations, {len(lines)} transmission lines.")
    add("--")
    add("-- Idempotent: stations upsert on name, lines on the unordered endpoint")
    add("-- pair, so re-running changes nothing and duplicates nothing.")
    add("")
    add("begin;")
    add("")

    # --- stations ----------------------------------------------------------
    add("insert into public.stations (name, type, latitude, longitude) values")
    rows = [
        f"  ({sql_str(s.name)}, {sql_str(sorted(s.types)[0])}, "
        f"{sql_num(s.latitude)}, {sql_num(s.longitude)})"
        for s in stations
    ]
    add(",\n".join(rows))
    add("on conflict (name) do update set")
    add("  type      = excluded.type,")
    add("  latitude  = excluded.latitude,")
    add("  longitude = excluded.longitude;")
    add("")

    # --- transmission lines ------------------------------------------------
    add("insert into public.transmission_lines (")
    add("  source_id, destination_id, type, distance_km, voltage_kv,")
    add("  capacity_mw, loss_percent, energy_loss_mw, csv_row")
    add(")")
    add("select")
    add("  s.id, d.id, v.type, v.distance_km, v.voltage_kv,")
    add("  v.capacity_mw, v.loss_percent, v.energy_loss_mw, v.csv_row")
    add("from (values")

    value_rows = []
    for index, line in enumerate(lines):
        # The first row carries the casts that fix the column types for the
        # whole VALUES list; the rest inherit them.
        cast = "::text" if index == 0 else ""
        cast_num = "::double precision" if index == 0 else ""
        cast_int = "::integer" if index == 0 else ""
        value_rows.append(
            f"  ({sql_str(line.source)}{cast}, {sql_str(line.destination)}{cast}, "
            f"{sql_str(line.line_type)}{cast}, "
            f"{sql_num(line.distance_km)}{cast_num}, {sql_num(line.voltage_kv)}{cast_num}, "
            f"{sql_num(line.capacity_mw)}{cast_num}, {sql_num(line.loss_percent)}{cast_num}, "
            f"{sql_num(line.energy_loss_mw)}{cast_num}, {line.row_number}{cast_int})"
        )
    add(",\n".join(value_rows))

    add(") as v (")
    add("  source, destination, type, distance_km, voltage_kv,")
    add("  capacity_mw, loss_percent, energy_loss_mw, csv_row")
    add(")")
    add("join public.stations s on s.name = v.source")
    add("join public.stations d on d.name = v.destination")
    add("on conflict (least(source_id, destination_id), greatest(source_id, destination_id))")
    add("do update set")
    add("  type           = excluded.type,")
    add("  distance_km    = excluded.distance_km,")
    add("  voltage_kv     = excluded.voltage_kv,")
    add("  capacity_mw    = excluded.capacity_mw,")
    add("  loss_percent   = excluded.loss_percent,")
    add("  energy_loss_mw = excluded.energy_loss_mw,")
    add("  csv_row        = excluded.csv_row;")
    add("")

    # --- assert the load matches the dataset -------------------------------
    add("-- Fail the transaction if the row counts do not match the CSV.")
    add("do $$")
    add("declare")
    add("  station_count int;")
    add("  line_count    int;")
    add("begin")
    add("  select count(*) into station_count from public.stations;")
    add("  select count(*) into line_count    from public.transmission_lines;")
    add(f"  if station_count <> {len(stations)} then")
    add(f"    raise exception 'expected {len(stations)} stations, found %', station_count;")
    add("  end if;")
    add(f"  if line_count <> {len(lines)} then")
    add(f"    raise exception 'expected {len(lines)} transmission lines, found %', line_count;")
    add("  end if;")
    add("end $$;")
    add("")
    add("commit;")
    add("")

    return "\n".join(out)


def main() -> int:
    sql = build()
    OUTPUT.write_text(sql, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)} ({len(sql.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
