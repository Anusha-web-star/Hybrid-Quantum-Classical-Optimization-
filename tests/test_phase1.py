"""Phase 1 tests, run against the real dataset in data/.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import itertools
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase1.data_loader import DatasetError, load_dataset  # noqa: E402
from phase1.layout import compute_layout  # noqa: E402
from phase1.network import Network, NetworkError  # noqa: E402
from phase1.nn_tsp import SolverError, solve  # noqa: E402
from phase1.visualize import plot_route  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(data_dir=DATA_DIR)
        cls.network = Network(cls.dataset)

    def test_every_csv_row_is_kept(self):
        self.assertEqual(len(self.dataset.connections), len(self.dataset.raw))

    def test_stations_come_from_the_csv(self):
        frame = self.dataset.raw
        expected = set(frame["Source"].str.strip()) | set(
            frame["Destination"].str.strip()
        )
        self.assertEqual(set(self.dataset.stations), expected)

    def test_distances_match_the_csv(self):
        frame = self.dataset.raw
        for _, row in frame.iterrows():
            edge = self.network.edge_between(
                row["Source"].strip(), row["Destination"].strip()
            )
            self.assertIsNotNone(edge)
            self.assertLessEqual(edge.distance_km, float(row["Distance_km"]) + 1e-9)

    def test_optional_attributes_are_carried_through(self):
        coverage = self.dataset.attribute_coverage()
        for key in ("Voltage_kV", "Capacity_MW", "Loss_Percent", "Energy_Loss_MW"):
            self.assertIn(key, coverage)

    def test_missing_file_is_reported(self):
        with self.assertRaises(DatasetError):
            load_dataset(os.path.join(DATA_DIR, "does_not_exist.csv"))

    def test_missing_required_column_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Source,Destination\nA,B\n")
            with self.assertRaises(DatasetError):
                load_dataset(path)

    def test_row_with_missing_values_is_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sparse.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Source,Destination,Distance_km,Capacity_MW\n")
                handle.write("A,B,10,\n")
                handle.write("B,C,,500\n")  # no distance
            dataset = load_dataset(path)
            self.assertEqual(len(dataset.connections), 2)
            self.assertEqual(set(dataset.stations), {"A", "B", "C"})
            self.assertEqual(len(dataset.routable_connections), 1)
            self.assertTrue(dataset.warnings)


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = Network(load_dataset(data_dir=DATA_DIR))

    def test_network_is_connected(self):
        self.assertTrue(self.network.is_connected)
        self.network.require_connected()  # must not raise

    def test_graph_is_undirected(self):
        for edge in self.network.edges.values():
            self.assertIn(edge.b, self.network.adjacency[edge.a])
            self.assertIn(edge.a, self.network.adjacency[edge.b])

    def test_shortest_path_is_symmetric_and_real(self):
        a, b = self.network.names[0], self.network.names[-1]
        self.assertAlmostEqual(
            self.network.travel_cost(a, b), self.network.travel_cost(b, a), places=6
        )
        path = self.network.travel_path(a, b)
        self.assertEqual(path[0], a)
        self.assertEqual(path[-1], b)
        # Every hop of the path is a real transmission line.
        walked = 0.0
        for x, y in zip(path, path[1:]):
            edge = self.network.edge_between(x, y)
            self.assertIsNotNone(edge)
            walked += edge.distance_km
        self.assertAlmostEqual(walked, self.network.travel_cost(a, b), places=6)

    def test_disconnected_network_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "split.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Source,Destination,Distance_km\nA,B,5\nC,D,7\n")
            network = Network(load_dataset(path))
            self.assertFalse(network.is_connected)
            with self.assertRaises(NetworkError):
                network.require_connected()
            with self.assertRaises(NetworkError):
                solve(network, "A")


class NearestNeighbourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = Network(load_dataset(data_dir=DATA_DIR))

    def test_visits_every_station_exactly_once_and_returns(self):
        result = solve(self.network, self.network.names[0])
        self.assertEqual(len(result.order), len(self.network.names))
        self.assertEqual(len(set(result.order)), len(result.order))
        self.assertEqual(set(result.order), set(self.network.names))
        self.assertEqual(result.closed_route[0], result.closed_route[-1])
        self.assertEqual(result.closed_route[0], result.start)

    def test_leg_distances_sum_to_the_total(self):
        result = solve(self.network, "Mysuru Substation")
        self.assertAlmostEqual(
            sum(leg.distance_km for leg in result.legs),
            result.total_distance_km,
            places=6,
        )
        self.assertEqual(len(result.legs), len(self.network.names))

    def test_greedy_choice_is_actually_the_nearest(self):
        result = solve(self.network, "Kaiga Nuclear Power Station")
        visited = {result.start}
        for leg in result.legs[:-1]:
            remaining = set(self.network.names) - visited
            best = min(self.network.travel_cost(leg.origin, n) for n in remaining)
            self.assertAlmostEqual(leg.distance_km, best, places=6)
            visited.add(leg.destination)

    def test_execution_time_is_recorded(self):
        result = solve(self.network, self.network.names[0])
        self.assertGreater(result.execution_time_s, 0.0)

    def test_every_start_station_produces_a_valid_tour(self):
        for name in self.network.names:
            result = solve(self.network, name)
            self.assertEqual(set(result.order), set(self.network.names))
            self.assertGreater(result.total_distance_km, 0.0)

    def test_result_is_deterministic(self):
        first = solve(self.network, "Hassan Substation")
        second = solve(self.network, "Hassan Substation")
        self.assertEqual(first.order, second.order)
        self.assertAlmostEqual(
            first.total_distance_km, second.total_distance_km, places=9
        )

    def test_case_insensitive_and_partial_start_names(self):
        self.assertEqual(
            solve(self.network, "mysuru substation").start, "Mysuru Substation"
        )
        self.assertEqual(solve(self.network, "Kaiga").start,
                         "Kaiga Nuclear Power Station")

    def test_invalid_start_station_is_rejected(self):
        for bad in ("Atlantis Power Plant", "", "   "):
            with self.assertRaises(SolverError):
                solve(self.network, bad)

    def test_ambiguous_start_station_is_rejected(self):
        with self.assertRaises(SolverError):
            solve(self.network, "Substation")

    def test_physical_path_only_uses_real_lines(self):
        result = solve(self.network, "Belagavi Substation")
        path = result.physical_path
        self.assertEqual(path[0], result.start)
        self.assertEqual(path[-1], result.start)
        for a, b in zip(path, path[1:]):
            self.assertIsNotNone(self.network.edge_between(a, b))


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = Network(load_dataset(data_dir=DATA_DIR))

    @staticmethod
    def _closest_pair(positions):
        return min(
            math.dist(positions[a], positions[b])
            for a, b in itertools.combinations(sorted(positions), 2)
        )

    def test_every_station_is_placed(self):
        for mode in ("geographic", "force"):
            layout = compute_layout(self.network, mode=mode)
            self.assertEqual(set(layout.positions), set(self.network.names))

    def test_geographic_layout_has_no_overlapping_nodes(self):
        layout = compute_layout(self.network, mode="geographic")
        self.assertGreaterEqual(
            self._closest_pair(layout.positions),
            layout.min_separation * 0.999,
        )

    def test_force_layout_has_no_overlapping_nodes(self):
        layout = compute_layout(self.network, mode="force")
        self.assertGreaterEqual(
            self._closest_pair(layout.positions),
            layout.min_separation * 0.999,
        )

    def test_true_coordinates_are_preserved_untouched(self):
        layout = compute_layout(self.network, mode="geographic")
        for name, (x, y) in layout.true_positions.items():
            station = self.network.stations[name]
            self.assertEqual((x, y), (station.longitude, station.latitude))

    def test_layout_stays_close_to_real_geography(self):
        """Spacing must not turn the map into a different country."""
        layout = compute_layout(self.network, mode="geographic")
        span = layout.span
        for name, true_point in layout.true_positions.items():
            self.assertLess(
                math.dist(layout.positions[name], true_point), span * 0.06
            )

    def test_layout_is_deterministic(self):
        for mode in ("geographic", "force"):
            first = compute_layout(self.network, mode=mode).positions
            second = compute_layout(self.network, mode=mode).positions
            self.assertEqual(first, second)

    def test_auto_falls_back_to_force_without_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nocoords.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Source,Destination,Distance_km\n")
                handle.write("A,B,10\nB,C,12\nC,A,9\n")
            layout = compute_layout(Network(load_dataset(path)))
            self.assertEqual(layout.mode, "force-directed")
            self.assertEqual(set(layout.positions), {"A", "B", "C"})

    def test_stations_without_coordinates_are_still_placed(self):
        """A partly-geocoded dataset keeps every station on the map."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "partial.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "Source,Destination,Source_Latitude,Source_Longitude,"
                    "Destination_Latitude,Destination_Longitude,Distance_km\n"
                )
                handle.write("A,B,12.0,74.0,13.0,75.0,10\n")
                handle.write("B,C,13.0,75.0,,,12\n")
            layout = compute_layout(Network(load_dataset(path)))
            self.assertEqual(layout.mode, "geographic")
            self.assertEqual(set(layout.positions), {"A", "B", "C"})
            self.assertIn("C", layout.placed_without_coordinates)


class VisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = Network(load_dataset(data_dir=DATA_DIR))
        cls.result = solve(cls.network, cls.network.names[0])

    def test_plot_is_written_for_both_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("geographic", "force"):
                path = plot_route(
                    self.network, self.result,
                    os.path.join(tmp, f"map_{mode}.png"),
                    layout_mode=mode,
                )
                self.assertTrue(os.path.isfile(path))
                self.assertGreater(os.path.getsize(path), 10_000)

    def test_plot_without_labels_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = plot_route(
                self.network, self.result, os.path.join(tmp, "plain.png"),
                show_labels=False,
            )
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
