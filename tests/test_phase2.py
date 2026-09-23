"""Phase 2 tests - the QAOA pipeline against the real dataset.

Everything here uses the actual CSV. No station and no distance is invented.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from itertools import permutations, product
from pathlib import Path
from unittest import mock

from phase1.data_loader import load_dataset
from phase1.network import Network

from phase2 import credentials
from phase2.backends import BackendError, SimulatorRunner
from phase2.instance import build_instance
from phase2.ising import qubo_to_ising
from phase2.qaoa import run_qaoa, validate_tour
from phase2.qubo import build_tsp_qubo
from phase2.reference import brute_force_optimum, nearest_neighbour

START = "Mysuru Substation"


class Phase2TestCase(unittest.TestCase):
    """Shared dataset, loaded once."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.network = Network(cls.dataset)
        cls.instance = build_instance(cls.network, START, size=4)


class TestInstance(Phase2TestCase):

    def test_stations_come_from_the_dataset(self):
        for name in self.instance.names:
            self.assertIn(name, self.dataset.stations)

    def test_start_is_first_and_size_matches(self):
        self.assertEqual(self.instance.names[0], START)
        self.assertEqual(self.instance.size, 4)
        self.assertEqual(len(set(self.instance.names)), 4)

    def test_matrix_is_symmetric_finite_and_zero_on_the_diagonal(self):
        for i in range(self.instance.size):
            self.assertEqual(self.instance.distance(i, i), 0.0)
            for j in range(self.instance.size):
                self.assertLess(self.instance.distance(i, j), float("inf"))
                self.assertAlmostEqual(
                    self.instance.distance(i, j), self.instance.distance(j, i)
                )

    def test_costs_are_the_phase_1_travel_costs(self):
        """The QAOA cost function must be the one Nearest Neighbour optimizes."""
        for i, a in enumerate(self.instance.names):
            for j, b in enumerate(self.instance.names):
                self.assertAlmostEqual(
                    self.instance.distance(i, j), self.network.travel_cost(a, b)
                )

    def test_qubit_count(self):
        self.assertEqual(self.instance.num_qubits, 9)

    def test_explicit_station_list_is_honoured(self):
        instance = build_instance(
            self.network, START,
            stations=["Hassan Substation", "Mangaluru Substation"],
        )
        self.assertEqual(instance.names[0], START)
        self.assertEqual(set(instance.names),
                         {START, "Hassan Substation", "Mangaluru Substation"})


class TestFullDatasetIsPreserved(Phase2TestCase):
    """Phase 2 takes a subset FROM the full network; it never replaces it."""

    def test_the_full_network_is_still_26_stations_and_38_lines(self):
        summary = self.network.summary()
        self.assertEqual(summary["stations"], 26)
        self.assertEqual(summary["routable_lines"], 38)
        self.assertEqual(summary["components"], 1)

    def test_phase_1_still_tours_every_station_in_the_full_network(self):
        """Phase 1 must keep solving the whole network, not the QAOA subset."""
        from phase1.nn_tsp import solve

        result = solve(self.network, START)
        self.assertEqual(result.stations_visited, 26)
        self.assertEqual(sorted(result.order), sorted(self.network.names))
        self.assertEqual(result.closed_route[0], result.closed_route[-1])

    def test_building_an_instance_does_not_mutate_the_network(self):
        before_stations = list(self.network.names)
        before_edges = dict(self.network.edges)
        build_instance(self.network, START, size=5)
        self.assertEqual(list(self.network.names), before_stations)
        self.assertEqual(dict(self.network.edges), before_edges)

    def test_the_instance_records_the_full_network_it_came_from(self):
        instance = build_instance(self.network, START, size=5)
        self.assertEqual(instance.total_stations, 26)
        self.assertEqual(instance.total_lines, 38)
        self.assertTrue(instance.is_subset)
        self.assertEqual(instance.full_network_qubits, 625)

    def test_no_station_is_invented_or_duplicated(self):
        instance = build_instance(self.network, START, size=5)
        self.assertEqual(len(instance.names), len(set(instance.names)))
        for name in instance.names:
            self.assertIn(name, self.network.names)

    def test_qubit_growth_is_quadratic_in_the_station_count(self):
        """The O(n^2) claim in the docs, asserted."""
        for size in (3, 4, 5, 6):
            instance = build_instance(self.network, START, size=size)
            self.assertEqual(instance.num_qubits, (size - 1) ** 2)

    def test_output_states_the_run_is_a_subset_and_claims_no_more(self):
        from phase2.main import print_scope

        instance = build_instance(self.network, START, size=5)
        captured = io.StringIO()
        with redirect_stdout(captured):
            print_scope(instance)
        output = captured.getvalue()
        self.assertIn("5 of the 26 stations", output)
        self.assertIn("does not solve the full 26-station", output)
        self.assertIn("625 qubits", output)

    def test_a_full_size_instance_is_not_labelled_a_subset(self):
        instance = build_instance(self.network, START, size=26)
        self.assertFalse(instance.is_subset)
        captured = io.StringIO()
        with redirect_stdout(captured):
            from phase2.main import print_scope
            print_scope(instance)
        self.assertEqual(captured.getvalue(), "")


class TestQubo(Phase2TestCase):

    def setUp(self):
        self.qubo, self.encoding, self.penalty = build_tsp_qubo(self.instance)

    def _bits_for(self, perm):
        bits = [0] * self.qubo.num_vars
        for position, station in enumerate(perm, start=1):
            bits[self.encoding.var(station, position)] = 1
        return bits

    def test_feasible_energy_equals_the_tour_distance(self):
        """On a valid permutation the penalties cancel and only the tour is left."""
        for perm in permutations(range(1, self.instance.size)):
            bits = self._bits_for(perm)
            order = (0,) + perm + (0,)
            distance = sum(
                self.instance.distance(a, b) for a, b in zip(order, order[1:])
            )
            self.assertAlmostEqual(self.qubo.energy(bits), distance, places=9)

    def test_decode_round_trips(self):
        for perm in permutations(range(1, self.instance.size)):
            order = self.encoding.decode(self._bits_for(perm))
            self.assertEqual(order, [0] + list(perm) + [0])

    def test_decode_rejects_invalid_assignments(self):
        self.assertIsNone(self.encoding.decode([0] * self.qubo.num_vars))
        self.assertIsNone(self.encoding.decode([1] * self.qubo.num_vars))
        two_in_one_row = [0] * self.qubo.num_vars
        two_in_one_row[self.encoding.var(1, 1)] = 1
        two_in_one_row[self.encoding.var(1, 2)] = 1
        self.assertIsNone(self.encoding.decode(two_in_one_row))

    def test_penalty_makes_every_invalid_state_worse_than_every_tour(self):
        worst_tour = max(
            self.qubo.energy(self._bits_for(p))
            for p in permutations(range(1, self.instance.size))
        )
        cheapest_invalid = min(
            self.qubo.energy(bits)
            for bits in product([0, 1], repeat=self.qubo.num_vars)
            if self.encoding.decode(bits) is None
        )
        self.assertLess(worst_tour, cheapest_invalid)


class TestIsing(Phase2TestCase):

    def test_hamiltonian_diagonal_reproduces_the_qubo(self):
        """x -> (1 - z)/2 must be exact for every assignment, not just tours."""
        qubo, _encoding, _penalty = build_tsp_qubo(self.instance)
        hamiltonian, constant = qubo_to_ising(qubo)
        n = qubo.num_vars
        labels = [str(p) for p in hamiltonian.paulis]
        coeffs = [complex(c).real for c in hamiltonian.coeffs]

        for bits in product([0, 1], repeat=n):
            spins = [1 - 2 * b for b in bits]
            energy = constant
            for label, coeff in zip(labels, coeffs):
                product_of_spins = 1
                for qubit in range(n):
                    if label[n - 1 - qubit] == "Z":
                        product_of_spins *= spins[qubit]
                energy += coeff * product_of_spins
            self.assertAlmostEqual(energy, qubo.energy(bits), places=7)

    def test_hamiltonian_has_no_identity_term(self):
        qubo, _encoding, _penalty = build_tsp_qubo(self.instance)
        hamiltonian, _constant = qubo_to_ising(qubo)
        for pauli in hamiltonian.paulis:
            self.assertIn("Z", str(pauli))


class TestReference(Phase2TestCase):

    def test_nearest_neighbour_uses_the_same_stations(self):
        reference = nearest_neighbour(self.network, self.instance)
        self.assertEqual(reference.route[0], START)
        self.assertEqual(reference.route[-1], START)
        self.assertEqual(set(reference.route), set(self.instance.names))

    def test_brute_force_is_never_worse_than_nearest_neighbour(self):
        optimum = brute_force_optimum(self.instance)
        heuristic = nearest_neighbour(self.network, self.instance)
        self.assertLessEqual(
            optimum.total_distance_km, heuristic.total_distance_km + 1e-9
        )

    def test_brute_force_route_is_a_valid_tour(self):
        optimum = brute_force_optimum(self.instance)
        self.assertEqual(optimum.route[0], START)
        self.assertEqual(optimum.route[-1], START)
        self.assertEqual(sorted(optimum.route[:-1]), sorted(self.instance.names))


class TestQaoaSimulator(Phase2TestCase):
    """The end-to-end run. Kept small so the suite stays quick."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = run_qaoa(
            cls.instance,
            reps=1, shots=512, maxiter=25, restarts=1, seed=11,
            runner=SimulatorRunner(seed=11),
        )
        cls.optimum = brute_force_optimum(cls.instance)

    def test_reports_the_simulator_backend(self):
        self.assertEqual(self.result.mode, "simulator")
        self.assertEqual(self.result.backend_name, "aer_simulator")
        self.assertEqual(self.result.job_ids, [])

    def test_returns_a_validated_tour(self):
        self.assertTrue(self.result.valid)
        self.assertTrue(all(passed for _, passed in self.result.checks))

    def test_route_is_a_closed_tour_over_the_instance(self):
        route = self.result.route
        self.assertEqual(route[0], START)
        self.assertEqual(route[-1], START)
        self.assertEqual(sorted(route[:-1]), sorted(self.instance.names))

    def test_reported_distance_matches_the_route(self):
        self.assertAlmostEqual(
            self.result.total_distance_km,
            self.instance.route_distance(self.result.route),
            places=9,
        )

    def test_result_is_feasible_but_never_claimed_optimal(self):
        """QAOA is approximate: it may not beat the optimum, and never below it."""
        self.assertGreaterEqual(
            self.result.total_distance_km,
            self.optimum.total_distance_km - 1e-9,
        )

    def test_circuit_size_matches_the_encoding(self):
        self.assertEqual(self.result.num_qubits, self.instance.num_qubits)
        self.assertGreater(self.result.evaluations, 0)
        self.assertGreater(self.result.total_samples, 0)

    def test_run_is_reproducible_for_a_fixed_seed(self):
        again = run_qaoa(
            self.instance,
            reps=1, shots=512, maxiter=25, restarts=1, seed=11,
            runner=SimulatorRunner(seed=11),
        )
        self.assertEqual(again.route, self.result.route)
        self.assertAlmostEqual(
            again.total_distance_km, self.result.total_distance_km, places=9
        )


class TestValidation(Phase2TestCase):

    def test_a_missing_tour_fails_validation(self):
        self.assertFalse(all(p for _, p in validate_tour(self.instance, None)))

    def test_a_tour_that_skips_a_station_fails_validation(self):
        checks = validate_tour(self.instance, [0, 1, 2, 0])
        self.assertFalse(all(passed for _, passed in checks))

    def test_a_tour_that_does_not_close_fails_validation(self):
        checks = validate_tour(self.instance, [0, 1, 2, 3])
        self.assertFalse(all(passed for _, passed in checks))


class TestCredentialConfig(unittest.TestCase):
    """The IBM credential plumbing: env-only, never leaked, never committed."""

    FAKE_TOKEN = "fake-token-value-do-not-use-0123456789"

    def test_gitignore_keeps_env_out_of_commits(self):
        self.assertTrue(
            credentials.gitignore_covers_env(),
            ".gitignore must list .env so a real key can never be committed.",
        )

    def test_env_example_documents_the_required_variables(self):
        text = (credentials.PROJECT_ROOT / ".env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("IBM_QUANTUM_TOKEN=", text)
        self.assertIn("IBM_QUANTUM_INSTANCE=", text)

    def test_env_example_holds_no_actual_values(self):
        """The committed template must never carry a real key."""
        text = (credentials.PROJECT_ROOT / ".env.example").read_text(
            encoding="utf-8"
        )
        for name, _required, _hint in credentials.CREDENTIAL_VARS:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"{name}="):
                    self.assertEqual(
                        stripped, f"{name}=",
                        f"{name} in .env.example must be left empty.",
                    )

    def test_parse_handles_comments_quotes_and_export(self):
        parsed = credentials.parse_env_file(
            "\n".join([
                "# a comment",
                "",
                "IBM_QUANTUM_TOKEN=plain",
                'IBM_QUANTUM_INSTANCE="quoted"',
                "export IBM_QUANTUM_CHANNEL=ibm_quantum_platform",
                "not-a-pair",
            ])
        )
        self.assertEqual(parsed["IBM_QUANTUM_TOKEN"], "plain")
        self.assertEqual(parsed["IBM_QUANTUM_INSTANCE"], "quoted")
        self.assertEqual(parsed["IBM_QUANTUM_CHANNEL"], "ibm_quantum_platform")
        self.assertNotIn("not-a-pair", parsed)

    def test_real_environment_wins_over_the_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder) / ".env"
            env_path.write_text(
                "IBM_QUANTUM_TOKEN=from-file\nIBM_QUANTUM_BACKEND=from-file\n",
                encoding="utf-8",
            )
            saved = {k: os.environ.get(k)
                     for k in ("IBM_QUANTUM_TOKEN", "IBM_QUANTUM_BACKEND")}
            try:
                os.environ["IBM_QUANTUM_TOKEN"] = "from-environment"
                os.environ.pop("IBM_QUANTUM_BACKEND", None)
                loaded = credentials.load_env_file(env_path)
                self.assertEqual(
                    os.environ["IBM_QUANTUM_TOKEN"], "from-environment"
                )
                self.assertEqual(os.environ["IBM_QUANTUM_BACKEND"], "from-file")
                self.assertNotIn("IBM_QUANTUM_TOKEN", loaded)
                self.assertIn("IBM_QUANTUM_BACKEND", loaded)
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_a_missing_env_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(
                credentials.load_env_file(Path(folder) / "absent.env"), []
            )

    def test_the_token_value_is_never_described(self):
        described = credentials.describe_value(
            credentials.TOKEN_VAR, self.FAKE_TOKEN
        )
        self.assertNotIn(self.FAKE_TOKEN, described)
        self.assertIn(str(len(self.FAKE_TOKEN)), described)

    def test_status_never_carries_the_token_value(self):
        saved = os.environ.get(credentials.TOKEN_VAR)
        try:
            os.environ[credentials.TOKEN_VAR] = self.FAKE_TOKEN
            for row in credentials.credential_status(load_file=False):
                self.assertNotIn(self.FAKE_TOKEN, " ".join(str(f) for f in row))
        finally:
            if saved is None:
                os.environ.pop(credentials.TOKEN_VAR, None)
            else:
                os.environ[credentials.TOKEN_VAR] = saved

    def test_check_ibm_prints_no_secret_and_contacts_nothing(self):
        from phase2.main import main as phase2_main

        saved = os.environ.get(credentials.TOKEN_VAR)
        try:
            os.environ[credentials.TOKEN_VAR] = self.FAKE_TOKEN
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = phase2_main(["--check-ibm"])
            output = captured.getvalue()
            self.assertEqual(code, 0)
            self.assertNotIn(self.FAKE_TOKEN, output)
            self.assertIn(credentials.TOKEN_VAR, output)
            self.assertIn("value hidden", output)
        finally:
            if saved is None:
                os.environ.pop(credentials.TOKEN_VAR, None)
            else:
                os.environ[credentials.TOKEN_VAR] = saved


class TestHybridFullNetwork(Phase2TestCase):
    """The hybrid must produce a COMPLETE, valid 26-station tour."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from phase1.nn_tsp import solve
        from phase2.backends import SimulatorRunner
        from phase2.hybrid import hybrid_solve

        cls.nn = solve(cls.network, START)
        cls.hybrid = hybrid_solve(
            cls.network, cls.nn.order, SimulatorRunner(seed=3),
            window=3, sweeps=1, reps=1, shots=256, maxiter=12,
            restarts=1, seed=3,
        )

    def test_result_covers_all_26_stations_exactly_once(self):
        order = self.hybrid.tour.order
        self.assertEqual(len(order), 26)
        self.assertEqual(len(set(order)), 26)
        self.assertEqual(sorted(order), sorted(self.network.names))

    def test_result_starts_and_ends_at_the_requested_station(self):
        closed = self.hybrid.tour.closed_route
        self.assertEqual(closed[0], START)
        self.assertEqual(closed[-1], START)
        self.assertEqual(len(closed), 27)

    def test_every_validation_check_passes(self):
        from phase2.hybrid import validate_full_tour

        checks = validate_full_tour(
            self.network, self.hybrid.tour, START, self.network.names
        )
        for label, passed in checks:
            self.assertTrue(passed, f"failed check: {label}")

    def test_reported_distance_matches_the_route(self):
        from phase2.hybrid import tour_length

        self.assertAlmostEqual(
            self.hybrid.total_distance_km,
            tour_length(self.network, self.hybrid.tour.order),
            places=6,
        )

    def test_legs_use_the_networks_own_travel_costs(self):
        for leg in self.hybrid.tour.legs:
            self.assertAlmostEqual(
                leg.distance_km,
                self.network.travel_cost(leg.origin, leg.destination),
            )

    def test_hybrid_never_returns_a_longer_tour_than_it_started_from(self):
        self.assertLessEqual(
            self.hybrid.total_distance_km,
            self.hybrid.start_distance_km + 1e-9,
        )

    def test_subproblem_size_matches_the_window(self):
        self.assertEqual(self.hybrid.qubits_per_subproblem, 9)
        self.assertGreater(self.hybrid.subproblems_solved, 0)

    def test_window_must_fit_in_the_tour(self):
        from phase2.backends import SimulatorRunner
        from phase2.hybrid import hybrid_solve

        with self.assertRaises(ValueError):
            hybrid_solve(self.network, self.nn.order[:4],
                         SimulatorRunner(seed=1), window=9)


class TestPruningPreservesResults(Phase2TestCase):
    """Don't-look-bits must save work without changing the answer."""

    def _run(self, prune):
        from phase2.backends import SimulatorRunner
        from phase2.hybrid import hybrid_solve

        from phase1.nn_tsp import solve
        nn = solve(self.network, START)
        return hybrid_solve(
            self.network, nn.order, SimulatorRunner(seed=5),
            window=3, sweeps=4, prune=prune,
            reps=1, shots=512, maxiter=15, restarts=1, seed=5,
        )

    def test_pruned_run_skips_windows_and_stays_valid(self):
        from phase2.hybrid import validate_full_tour

        pruned = self._run(prune=True)
        self.assertGreater(pruned.subproblems_skipped, 0)
        for label, passed in validate_full_tour(
            self.network, pruned.tour, START, self.network.names
        ):
            self.assertTrue(passed, f"failed check: {label}")

    def test_unpruned_run_skips_nothing(self):
        unpruned = self._run(prune=False)
        self.assertEqual(unpruned.subproblems_skipped, 0)

    def test_pruning_does_the_same_work_an_exact_subsolver_would(self):
        """The pruning rule itself, checked deterministically.

        A window whose seven stations are all unchanged since it last failed
        cannot improve, so pruning must reach the same tour as full sweeps.
        """
        from itertools import permutations

        cost = self.network.travel_cost

        def segment(seq):
            return sum(cost(a, b) for a, b in zip(seq, seq[1:]))

        def tour_km(order):
            return sum(cost(order[i], order[(i + 1) % len(order)])
                       for i in range(len(order)))

        from phase1.nn_tsp import solve
        start_order = solve(self.network, START).order
        width = 4

        def search(prune):
            tour = list(start_order)
            dirty = set(tour)
            for _ in range(12):
                improved = False
                for offset in range(len(tour)):
                    entry = tour[offset % len(tour)]
                    slots = [(offset + 1 + k) % len(tour) for k in range(width)]
                    free = [tour[i] for i in slots]
                    exit_station = tour[(offset + 1 + width) % len(tour)]
                    involved = [entry] + free + [exit_station]
                    if prune and not any(x in dirty for x in involved):
                        continue
                    best, best_km = None, segment(involved)
                    for candidate in permutations(free):
                        km = segment([entry] + list(candidate) + [exit_station])
                        if km < best_km - 1e-9:
                            best, best_km = candidate, km
                    if best:
                        for slot, name in zip(slots, best):
                            tour[slot] = name
                        improved = True
                        if prune:
                            dirty.update(involved)
                    elif prune:
                        dirty.discard(entry)
                if not improved:
                    break
            return tour_km(tour)

        self.assertAlmostEqual(search(prune=True), search(prune=False), places=6)


class TestPathQubo(Phase2TestCase):
    """The open-path subproblem QUBO the hybrid hands to QAOA."""

    def test_feasible_energy_equals_the_segment_length(self):
        from phase2.qubo import build_path_qubo

        entry, exit_ = "Mysuru Substation", "Hassan Substation"
        free = ["Tumakuru Substation", "Shivamogga Substation",
                "Mangaluru Substation"]
        cost = self.network.travel_cost
        entry_cost = [cost(entry, f) for f in free]
        exit_cost = [cost(f, exit_) for f in free]
        pair_cost = [[cost(a, b) for b in free] for a in free]
        penalty = 10_000.0
        qubo, encoding = build_path_qubo(entry_cost, exit_cost, pair_cost, penalty)

        for perm in permutations(range(len(free))):
            bits = [0] * qubo.num_vars
            for position, station in enumerate(perm):
                bits[encoding.var(station, position)] = 1
            sequence = [entry] + [free[i] for i in perm] + [exit_]
            expected = sum(cost(a, b) for a, b in zip(sequence, sequence[1:]))
            self.assertAlmostEqual(qubo.energy(bits), expected, places=9)
            self.assertEqual(encoding.decode(bits), list(perm))

    def test_decode_rejects_invalid_assignments(self):
        from phase2.qubo import build_path_qubo

        qubo, encoding = build_path_qubo([1.0, 2.0], [1.0, 2.0],
                                         [[0.0, 3.0], [3.0, 0.0]], 100.0)
        self.assertIsNone(encoding.decode([0] * qubo.num_vars))
        self.assertIsNone(encoding.decode([1] * qubo.num_vars))


class TestComparisonAndMaps(Phase2TestCase):

    def test_both_maps_share_identical_station_coordinates(self):
        """Requirement: the two route graphs must be visually comparable."""
        from phase2.visualize import same_layout

        self.assertTrue(same_layout(self.network, mode="auto"))

    def test_same_problem_checks_pass_for_two_full_tours(self):
        from phase1.nn_tsp import solve
        from phase2.comparison import same_problem_checks
        from phase2.hybrid import HybridResult, tour_result_from_order

        nn = solve(self.network, START)
        reversed_order = [nn.order[0]] + list(reversed(nn.order[1:]))
        stand_in = HybridResult(
            tour=tour_result_from_order(self.network, reversed_order, 0.0),
            start_distance_km=nn.total_distance_km, window=4, sweeps_run=1,
            subproblems_solved=0, subproblems_skipped=0,
            improvements_accepted=0, qaoa_evaluations=0,
            qubits_per_subproblem=16, execution_time_s=0.0,
        )
        for label, passed in same_problem_checks(
            self.network, nn, stand_in, START
        ):
            self.assertTrue(passed, f"failed check: {label}")

    def test_comparison_reports_improvement_and_never_claims_advantage(self):
        from phase2.comparison import Comparison

        comparison = Comparison(
            start=START, stations=26, lines=38, dataset_path="x",
            nn_distance_km=3017.795, nn_time_s=0.0006, nn_valid=True,
            nn_checks=[], hybrid_distance_km=2851.243, hybrid_time_s=170.0,
            hybrid_valid=True, hybrid_checks=[], hybrid_window=4,
            hybrid_qubits=16, hybrid_subproblems=52, hybrid_skipped=0,
            hybrid_accepted=5,
            hybrid_sweeps=2, hybrid_mode="simulator", hybrid_backend="Aer",
        )
        self.assertAlmostEqual(comparison.improvement_km, 166.552, places=3)
        self.assertAlmostEqual(comparison.improvement_percent, 5.519, places=2)
        self.assertEqual(comparison.winner, "hybrid")
        note = comparison.framing_note().lower()
        self.assertIn("no quantum advantage", note)
        self.assertIn("do not solve the whole tsp", note)

    @staticmethod
    def _comparison(nn_distance_km, hybrid_distance_km):
        from phase2.comparison import Comparison

        return Comparison(
            start=START, stations=26, lines=38, dataset_path="x",
            nn_distance_km=nn_distance_km, nn_time_s=0.0006, nn_valid=True,
            nn_checks=[], hybrid_distance_km=hybrid_distance_km,
            hybrid_time_s=170.0, hybrid_valid=True, hybrid_checks=[],
            hybrid_window=4, hybrid_qubits=16, hybrid_subproblems=52,
            hybrid_skipped=0, hybrid_accepted=5, hybrid_sweeps=2,
            hybrid_mode="simulator", hybrid_backend="Aer",
        )

    def test_difference_and_percentage_follow_from_the_displayed_distances(self):
        """The reported difference and percentage must be recomputable by hand.

        A reader sees two distances. Subtracting them, and dividing by the
        classical one, has to reproduce exactly the difference and the
        percentage Phase 2 prints - no hidden precision in between.
        """
        from phase2.comparison import DISTANCE_DECIMALS, PERCENT_DECIMALS

        # The raw solver floats carry more precision than is ever displayed.
        comparison = self._comparison(nn_distance_km=2554.0154821,
                                      hybrid_distance_km=2475.8767139)

        nn_shown = comparison.nn_distance_display
        hybrid_shown = comparison.hybrid_distance_display
        self.assertEqual(nn_shown, 2554.015)
        self.assertEqual(hybrid_shown, 2475.877)

        expected_km = round(nn_shown - hybrid_shown, DISTANCE_DECIMALS)
        expected_percent = round(expected_km / nn_shown * 100.0,
                                 PERCENT_DECIMALS)
        self.assertEqual(comparison.improvement_km, expected_km)
        self.assertEqual(comparison.improvement_percent, expected_percent)
        self.assertEqual(comparison.improvement_km, 78.138)
        self.assertEqual(comparison.improvement_percent, 3.06)

    def test_every_surface_reports_the_same_calculated_values(self):
        """Terminal, figure panel and table share one set of numbers."""
        comparison = self._comparison(nn_distance_km=2554.0154821,
                                      hybrid_distance_km=2475.8767139)

        rows = dict(
            (label, (classical, quantum))
            for label, classical, quantum in comparison.table_rows()
        )
        # The figure panel draws exactly these strings (phase2.visualize
        # renders comparison.table_rows()), and the terminal prints them too.
        self.assertEqual(rows["Total distance"],
                         ("2,554.015 km", "2,475.877 km"))
        self.assertEqual(rows["Improvement vs NN"][1],
                         "+78.138 km (+3.06%)")

        # The standalone terminal line uses the same two properties.
        terminal = (f"{comparison.improvement_km:+,.3f} km absolute, "
                    f"{comparison.improvement_percent:+.2f}% relative to NN")
        self.assertEqual(terminal, "+78.138 km absolute, +3.06% relative to NN")

        # And the map titles are drawn from the same displayed distances.
        self.assertEqual(f"{comparison.nn_distance_display:,.1f} km",
                         "2,554.0 km")
        self.assertEqual(f"{comparison.hybrid_distance_display:,.1f} km",
                         "2,475.9 km")

    def test_consistency_holds_when_the_classical_route_wins(self):
        """The identity must not depend on the sign of the difference."""
        from phase2.comparison import DISTANCE_DECIMALS, PERCENT_DECIMALS

        comparison = self._comparison(nn_distance_km=2475.877,
                                      hybrid_distance_km=2554.015)
        expected_km = round(2475.877 - 2554.015, DISTANCE_DECIMALS)
        self.assertEqual(comparison.improvement_km, expected_km)
        self.assertEqual(
            comparison.improvement_percent,
            round(expected_km / 2475.877 * 100.0, PERCENT_DECIMALS),
        )
        self.assertEqual(comparison.winner, "classical")

    def test_printed_route_shows_every_station_and_closes_the_tour(self):
        """The terminal route must be complete, not a summary.

        All 26 stations, the start repeated at the end, and nothing
        abbreviated: the line wrapping is presentation only.
        """
        from phase1.nn_tsp import solve
        from phase2.main import route_chain_lines

        closed = solve(self.network, START).closed_route
        lines = route_chain_lines(closed)

        # A wrapped line keeps its trailing arrow, so rejoining the lines with
        # a single space has to reproduce the chain character for character.
        rendered = " ".join(lines)
        self.assertEqual(rendered, " -> ".join(closed))

        self.assertEqual(len(closed), len(self.network.names) + 1)
        self.assertEqual(closed[0], START)
        self.assertEqual(closed[-1], START)
        for name in self.network.names:
            self.assertIn(name, rendered)
        self.assertNotIn("...", rendered)

    def test_both_printed_routes_span_the_same_network_and_start(self):
        """The two printed routes must be directly comparable."""
        from phase1.nn_tsp import solve
        from phase2.hybrid import HybridResult, tour_result_from_order
        from phase2.main import route_chain_lines

        nn = solve(self.network, START)
        reversed_order = [nn.order[0]] + list(reversed(nn.order[1:]))
        hybrid = HybridResult(
            tour=tour_result_from_order(self.network, reversed_order, 0.0),
            start_distance_km=nn.total_distance_km, window=4, sweeps_run=1,
            subproblems_solved=0, subproblems_skipped=0,
            improvements_accepted=0, qaoa_evaluations=0,
            qubits_per_subproblem=16, execution_time_s=0.0,
        )

        nn_route = " ".join(route_chain_lines(nn.closed_route))
        hybrid_route = " ".join(route_chain_lines(hybrid.tour.closed_route))
        for rendered, closed in ((nn_route, nn.closed_route),
                                 (hybrid_route, hybrid.tour.closed_route)):
            self.assertEqual(sorted(closed[:-1]), sorted(self.network.names))
            self.assertTrue(rendered.startswith(START))
            self.assertTrue(rendered.endswith(START))

    def test_validation_rejects_a_tour_that_skips_a_station(self):
        from phase1.nn_tsp import solve
        from phase2.hybrid import tour_result_from_order, validate_full_tour

        nn = solve(self.network, START)
        broken = tour_result_from_order(self.network, nn.order[:-1], 0.0)
        checks = validate_full_tour(
            self.network, broken, START, self.network.names
        )
        self.assertFalse(all(passed for _, passed in checks))


class TestPhase1RendererUnchanged(Phase2TestCase):

    def test_route_label_defaults_to_the_phase_1_wording(self):
        """Phase 2's legend override must not change Phase 1's own output."""
        import inspect

        from phase1.visualize import plot_route

        default = inspect.signature(plot_route).parameters["route_label"].default
        self.assertEqual(default, "Nearest Neighbour route (legs numbered)")


class TestOneCommandDefaults(unittest.TestCase):
    """`run_phase2.py` with no flags must run the FULL-network comparison."""

    def setUp(self):
        from phase2.main import build_parser
        self.parser = build_parser()

    def test_bare_invocation_selects_the_full_network_workflow(self):
        args = self.parser.parse_args([])
        self.assertFalse(args.subset,
                         "no flags must mean the full-network workflow")
        self.assertFalse(args.check_ibm)

    def test_bare_invocation_does_not_touch_ibm_hardware(self):
        args = self.parser.parse_args([])
        self.assertEqual(args.mode, "simulator")

    def test_default_window_is_practical_to_simulate(self):
        """The default must finish in about a minute, not 90."""
        args = self.parser.parse_args([])
        self.assertEqual(args.window, 4)
        self.assertEqual(args.window ** 2, 16)

    def test_default_start_is_unset_so_the_user_is_asked(self):
        args = self.parser.parse_args([])
        self.assertIsNone(args.start)

    def test_subset_mode_is_opt_in(self):
        args = self.parser.parse_args(["--subset"])
        self.assertTrue(args.subset)

    def test_full_flag_still_accepted_for_existing_commands(self):
        args = self.parser.parse_args(["--full"])
        self.assertFalse(args.subset)

    def test_full_workflow_draws_enough_shots_to_find_valid_orderings(self):
        """At W=4 only 24 of 65,536 bitstrings are valid orderings."""
        args = self.parser.parse_args([])
        self.assertGreaterEqual(args.hybrid_shots, 2048)


class TestIbmCredentials(unittest.TestCase):

    def test_missing_token_is_a_clean_backend_error(self):
        """No token must mean a clear message, never a hardcoded fallback.

        The developer's real `.env` is deliberately kept out of this test: it
        must exercise the missing-token path, never contact IBM.
        """
        from phase2 import backends as backends_module
        from phase2.backends import IBMRunner

        saved = os.environ.pop("IBM_QUANTUM_TOKEN", None)
        try:
            with mock.patch.object(backends_module, "load_env_file",
                                   return_value=[]):
                with self.assertRaises(BackendError) as caught:
                    IBMRunner()
            self.assertIn("IBM_QUANTUM_TOKEN", str(caught.exception))
        finally:
            if saved is not None:
                os.environ["IBM_QUANTUM_TOKEN"] = saved

    def test_no_credentials_are_hardcoded_in_the_source(self):
        import phase2.backends as backends

        with open(backends.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("token=\"", source)
        self.assertNotIn("token='", source)


if __name__ == "__main__":
    unittest.main()
