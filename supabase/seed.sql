-- GRIDOPT seed data - GENERATED, do not edit by hand.
-- Source: transmition_lines.csv.csv
-- Regenerate with: .venv\Scripts\python.exe supabase/generate_seed.py
-- Contents: 26 stations, 38 transmission lines.
--
-- Idempotent: stations upsert on name, lines on the unordered endpoint
-- pair, so re-running changes nothing and duplicates nothing.

begin;

insert into public.stations (name, type, latitude, longitude) values
  ('Belagavi Substation', 'substation', 15.8497, 74.4977),
  ('Bellary Thermal Power Station', 'thermal', 15.1421, 76.8747),
  ('Bengaluru (Kadabagere/Hoody) Substation', 'substation', 12.9716, 77.5946),
  ('Chitradurga Wind Cluster', 'wind', 14.23, 76.4),
  ('Davangere Substation', 'substation', 14.4644, 75.9218),
  ('Gadag Wind-Solar Hybrid Cluster', 'wind', 14.99, 75.63),
  ('Gerusoppa Power House', 'hydro', 14.205, 74.652),
  ('Hassan Substation', 'substation', 13.0072, 76.1004),
  ('Hubballi-Dharwad Substation', 'substation', 15.3647, 75.124),
  ('Kadra Power House', 'hydro', 14.802, 74.522),
  ('Kaiga Nuclear Power Station', 'nuclear', 14.864, 74.439),
  ('Kalaburagi Substation', 'substation', 17.3297, 76.8343),
  ('Kappatagudda Wind Cluster', 'wind', 15.35, 75.65),
  ('Kodasalli Power House', 'hydro', 14.848, 74.555),
  ('Linganamakki Dam Power House', 'hydro', 14.205, 74.833),
  ('Mangaluru Substation', 'substation', 12.9141, 74.856),
  ('Mysuru Substation', 'substation', 12.2958, 76.6394),
  ('Nagjhari Power House', 'hydro', 14.85, 74.605),
  ('Pavagada Solar Park (Shakti Sthala)', 'solar', 14.1, 77.28),
  ('Raichur Thermal Power Station', 'thermal', 16.2274, 77.3565),
  ('Sharavathy Generating Station', 'hydro', 14.228, 74.793),
  ('Shivamogga Substation', 'substation', 13.9299, 75.5681),
  ('Supa Dam Power House', 'hydro', 14.95, 74.68),
  ('Tumakuru Substation', 'substation', 13.3379, 77.1173),
  ('Varahi Underground Power House', 'hydro', 13.554, 74.933),
  ('Yermarus Thermal Power Station', 'thermal', 16.1913, 77.4363)
on conflict (name) do update set
  type      = excluded.type,
  latitude  = excluded.latitude,
  longitude = excluded.longitude;

insert into public.transmission_lines (
  source_id, destination_id, type, distance_km, voltage_kv,
  capacity_mw, loss_percent, energy_loss_mw, csv_row
)
select
  s.id, d.id, v.type, v.distance_km, v.voltage_kv,
  v.capacity_mw, v.loss_percent, v.energy_loss_mw, v.csv_row
from (values
  ('Belagavi Substation'::text, 'Supa Dam Power House'::text, 'substation'::text, 101.933::double precision, 110.0::double precision, 1353.809::double precision, 2.243::double precision, 30.366::double precision, 2::integer),
  ('Bellary Thermal Power Station', 'Chitradurga Wind Cluster', 'thermal', 113.549, 66.0, 1700.0, 2.498, 42.466, 3),
  ('Bellary Thermal Power Station', 'Pavagada Solar Park (Shakti Sthala)', 'thermal', 123.81, 220.0, 1700.0, 2.724, 46.308, 4),
  ('Bengaluru (Kadabagere/Hoody) Substation', 'Mysuru Substation', 'substation', 128.017, 220.0, 810.983, 2.816, 22.837, 5),
  ('Chitradurga Wind Cluster', 'Davangere Substation', 'wind', 57.733, 66.0, 550.0, 1.27, 6.985, 6),
  ('Chitradurga Wind Cluster', 'Pavagada Solar Park (Shakti Sthala)', 'wind', 95.971, 66.0, 550.0, 2.111, 11.611, 7),
  ('Chitradurga Wind Cluster', 'Shivamogga Substation', 'wind', 95.728, 66.0, 550.0, 2.106, 11.583, 8),
  ('Davangere Substation', 'Gadag Wind-Solar Hybrid Cluster', 'substation', 66.336, 66.0, 1490.929, 1.459, 21.753, 9),
  ('Davangere Substation', 'Shivamogga Substation', 'substation', 70.613, 220.0, 1229.736, 1.553, 19.098, 10),
  ('Gadag Wind-Solar Hybrid Cluster', 'Kappatagudda Wind Cluster', 'wind', 40.088, 66.0, 300.0, 0.882, 2.646, 11),
  ('Gerusoppa Power House', 'Sharavathy Generating Station', 'hydro', 15.412, 220.0, 240.0, 0.339, 0.814, 12),
  ('Hassan Substation', 'Mysuru Substation', 'substation', 98.373, 220.0, 252.567, 2.164, 5.466, 13),
  ('Hubballi-Dharwad Substation', 'Belagavi Substation', 'substation', 86.065, 220.0, 1680.508, 1.893, 31.812, 14),
  ('Hubballi-Dharwad Substation', 'Supa Dam Power House', 'substation', 66.311, 110.0, 1333.046, 1.459, 19.449, 15),
  ('Kadra Power House', 'Gerusoppa Power House', 'hydro', 67.843, 110.0, 150.0, 1.493, 2.24, 16),
  ('Kadra Power House', 'Kaiga Nuclear Power Station', 'hydro', 11.275, 110.0, 150.0, 0.248, 0.372, 17),
  ('Kaiga Nuclear Power Station', 'Kodasalli Power House', 'nuclear', 12.594, 110.0, 880.0, 0.277, 2.438, 18),
  ('Kalaburagi Substation', 'Yermarus Thermal Power Station', 'substation', 141.886, 220.0, 1373.424, 3.121, 42.865, 19),
  ('Kappatagudda Wind Cluster', 'Hubballi-Dharwad Substation', 'wind', 56.424, 66.0, 250.0, 1.241, 3.103, 20),
  ('Kodasalli Power House', 'Kadra Power House', 'hydro', 6.225, 110.0, 120.0, 0.137, 0.164, 21),
  ('Linganamakki Dam Power House', 'Gerusoppa Power House', 'hydro', 19.511, 66.0, 55.0, 0.429, 0.236, 22),
  ('Linganamakki Dam Power House', 'Varahi Underground Power House', 'hydro', 73.188, 66.0, 55.0, 1.61, 0.886, 23),
  ('Mangaluru Substation', 'Hassan Substation', 'substation', 135.243, 220.0, 307.544, 2.975, 9.149, 24),
  ('Mysuru Substation', 'Tumakuru Substation', 'substation', 126.934, 220.0, 829.625, 2.793, 23.171, 25),
  ('Nagjhari Power House', 'Kadra Power House', 'hydro', 10.397, 110.0, 900.0, 0.229, 2.061, 26),
  ('Nagjhari Power House', 'Kodasalli Power House', 'hydro', 5.379, 110.0, 900.0, 0.118, 1.062, 27),
  ('Pavagada Solar Park (Shakti Sthala)', 'Tumakuru Substation', 'solar', 86.545, 220.0, 2050.0, 1.904, 39.032, 28),
  ('Raichur Thermal Power Station', 'Bellary Thermal Power Station', 'thermal', 131.24, 220.0, 1720.0, 2.887, 49.656, 29),
  ('Raichur Thermal Power Station', 'Kalaburagi Substation', 'thermal', 134.588, 220.0, 1720.0, 2.961, 50.929, 30),
  ('Raichur Thermal Power Station', 'Yermarus Thermal Power Station', 'thermal', 9.419, 220.0, 1720.0, 0.207, 3.56, 31),
  ('Sharavathy Generating Station', 'Linganamakki Dam Power House', 'hydro', 5.013, 66.0, 1035.0, 0.11, 1.138, 32),
  ('Shivamogga Substation', 'Varahi Underground Power House', 'substation', 80.329, 220.0, 700.693, 1.767, 12.381, 33),
  ('Supa Dam Power House', 'Kodasalli Power House', 'hydro', 17.58, 110.0, 100.0, 0.387, 0.387, 34),
  ('Supa Dam Power House', 'Nagjhari Power House', 'hydro', 13.733, 110.0, 100.0, 0.302, 0.302, 35),
  ('Tumakuru Substation', 'Bengaluru (Kadabagere/Hoody) Substation', 'substation', 65.802, 220.0, 1601.359, 1.448, 23.188, 36),
  ('Tumakuru Substation', 'Hassan Substation', 'substation', 116.077, 220.0, 1143.061, 2.554, 29.194, 37),
  ('Varahi Underground Power House', 'Mangaluru Substation', 'hydro', 71.64, 220.0, 460.0, 1.576, 7.25, 38),
  ('Yermarus Thermal Power Station', 'Bellary Thermal Power Station', 'thermal', 131.248, 220.0, 1600.0, 2.887, 46.192, 39)
) as v (
  source, destination, type, distance_km, voltage_kv,
  capacity_mw, loss_percent, energy_loss_mw, csv_row
)
join public.stations s on s.name = v.source
join public.stations d on d.name = v.destination
on conflict (least(source_id, destination_id), greatest(source_id, destination_id))
do update set
  type           = excluded.type,
  distance_km    = excluded.distance_km,
  voltage_kv     = excluded.voltage_kv,
  capacity_mw    = excluded.capacity_mw,
  loss_percent   = excluded.loss_percent,
  energy_loss_mw = excluded.energy_loss_mw,
  csv_row        = excluded.csv_row;

-- Fail the transaction if the row counts do not match the CSV.
do $$
declare
  station_count int;
  line_count    int;
begin
  select count(*) into station_count from public.stations;
  select count(*) into line_count    from public.transmission_lines;
  if station_count <> 26 then
    raise exception 'expected 26 stations, found %', station_count;
  end if;
  if line_count <> 38 then
    raise exception 'expected 38 transmission lines, found %', line_count;
  end if;
end $$;

commit;
