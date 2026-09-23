"""Step 3 of the pipeline: Ising Hamiltonian -> QAOA -> a validated tour.

QAOA (Quantum Approximate Optimization Algorithm) prepares

    |psi(beta, gamma)> = prod_{l=1..p} [ exp(-i beta_l H_mixer) exp(-i gamma_l H_cost) ] |+>^n

and a classical optimizer (COBYLA) tunes the 2p angles to push the sampled
bitstrings towards low energies of `H_cost`. Every measured bitstring is decoded
back into a station ordering; orderings that are genuine permutations are scored
with the real `Distance_km` costs, and the best one is returned.

This is an approximate, heuristic method. It gives no guarantee of finding the
globally optimal tour, and the answer it returns is the best *valid* tour it
happened to measure - which is why the tour is validated before it is returned.

Scaling note: the Ising coefficients carry kilometre magnitudes (hundreds to
thousands), which would force absurdly small gamma angles. The Hamiltonian handed
to the circuit is therefore divided by its largest coefficient. This rescales the
angles only - every distance reported comes from the unscaled instance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from qiskit.circuit.library import qaoa_ansatz
from scipy.optimize import minimize

from .ising import qubo_to_ising
from .qubo import build_tsp_qubo


@dataclass
class QaoaResult:
    """Everything Phase 2 reports about one QAOA run."""

    # the answer
    route: list                     # station names, closed (start ... start)
    total_distance_km: float
    valid: bool
    checks: list = field(default_factory=list)

    # execution
    execution_time_s: float = 0.0
    mode: str = "simulator"
    backend_name: str = ""
    backend_description: str = ""
    job_ids: list = field(default_factory=list)
    job_status: str = None

    # the model
    num_qubits: int = 0
    reps: int = 0
    shots: int = 0
    penalty: float = 0.0
    qubo_terms: int = 0
    hamiltonian_terms: int = 0

    # search statistics
    evaluations: int = 0
    circuit_runs: int = 0
    total_samples: int = 0
    feasible_samples: int = 0
    distinct_feasible_tours: int = 0
    best_qubo_energy: float = None

    @property
    def feasible_fraction(self) -> float:
        if not self.total_samples:
            return 0.0
        return self.feasible_samples / self.total_samples


def _bits_from_bitstring(bitstring: str, num_vars: int) -> list:
    """Qiskit bitstrings are little-endian: rightmost character is qubit 0."""
    return [int(bitstring[num_vars - 1 - v]) for v in range(num_vars)]


class _TourSearch:
    """Decodes samples, scores valid tours, and remembers the best one seen."""

    def __init__(self, instance, qubo, encoding):
        self.instance = instance
        self.qubo = qubo
        self.encoding = encoding
        self.best_order = None
        self.best_distance = float("inf")
        self.best_energy = None
        self.total_samples = 0
        self.feasible_samples = 0
        self.seen_tours = set()

    def absorb(self, counts: dict) -> list:
        """Record a batch of samples; return (energy, count) pairs for the loop."""
        scored = []
        for bitstring, count in counts.items():
            bits = _bits_from_bitstring(bitstring, self.qubo.num_vars)
            energy = self.qubo.energy(bits)
            scored.append((energy, count))

            self.total_samples += count
            order = self.encoding.decode(bits)
            if order is None:
                continue
            self.feasible_samples += count
            self.seen_tours.add(tuple(order))
            distance = sum(
                self.instance.distance(a, b) for a, b in zip(order, order[1:])
            )
            if distance < self.best_distance:
                self.best_distance = distance
                self.best_order = order
                self.best_energy = energy
        return scored


def _cvar(scored: list, alpha: float) -> float:
    """Mean energy of the best `alpha` fraction of shots (alpha=1 -> plain mean).

    CVaR makes the optimizer chase the good tail of the distribution instead of
    the average, which matters here because most bitstrings violate the
    permutation constraints and sit at a high penalty energy.
    """
    total_shots = sum(count for _, count in scored)
    if not total_shots:
        return 0.0
    if alpha >= 1.0:
        return sum(e * c for e, c in scored) / total_shots

    budget = max(1, int(round(alpha * total_shots)))
    accumulated = 0.0
    taken = 0
    for energy, count in sorted(scored, key=lambda ec: ec[0]):
        use = min(count, budget - taken)
        accumulated += energy * use
        taken += use
        if taken >= budget:
            break
    return accumulated / taken


def solve_qubo_qaoa(
    qubo,
    decode,
    score,
    runner,
    *,
    reps: int = 1,
    shots: int = 512,
    maxiter: int = 40,
    restarts: int = 1,
    seed: int = 5,
    cvar_alpha: float = 0.25,
):
    """Run QAOA on any QUBO and return the best decoded, scored candidate.

    This is the reusable engine the hybrid full-network solver drives once per
    subproblem. `decode(bits)` turns an assignment into a candidate (or None if
    the bits are infeasible) and `score(candidate)` gives its real cost in km.

    Returns (best_candidate, best_score, evaluations). Same pipeline as
    `run_qaoa`: normalised Ising Hamiltonian, CVaR objective, COBYLA, and the
    best *feasible* sample kept across every shot drawn.
    """
    hamiltonian, _constant = qubo_to_ising(qubo)
    scale = max((abs(complex(c).real) for c in hamiltonian.coeffs), default=1.0)
    scale = scale or 1.0
    ansatz = qaoa_ansatz(hamiltonian * (1.0 / scale), reps=reps)

    circuit = ansatz.copy()
    circuit.measure_all()
    circuit = runner.prepare(circuit)

    best = {"candidate": None, "score": float("inf")}
    evaluations = 0

    def objective(params) -> float:
        nonlocal evaluations
        evaluations += 1
        counts = runner.sample(circuit, np.asarray(params, dtype=float), shots)
        scored = []
        for bitstring, count in counts.items():
            bits = _bits_from_bitstring(bitstring, qubo.num_vars)
            scored.append((qubo.energy(bits), count))
            candidate = decode(bits)
            if candidate is None:
                continue
            value = score(candidate)
            if value < best["score"]:
                best["score"] = value
                best["candidate"] = candidate
        return _cvar(scored, cvar_alpha)

    rng = np.random.default_rng(seed)
    for _ in range(max(1, restarts)):
        minimize(
            objective, rng.uniform(0.0, np.pi, ansatz.num_parameters),
            method="COBYLA", options={"maxiter": maxiter},
        )

    return best["candidate"], best["score"], evaluations


def validate_tour(instance, order: list) -> list:
    """Checks the tour must pass before Phase 2 will report it."""
    if order is None:
        return [("a valid tour was found", False)]
    body = order[:-1]
    return [
        ("closed tour - returns to the starting station",
         len(order) > 1 and order[0] == order[-1] and order[0] == 0),
        (f"all {instance.size} stations visited exactly once",
         sorted(body) == list(range(instance.size))),
        ("every leg uses a real transmission-line cost",
         all(instance.distance(a, b) < float("inf")
             for a, b in zip(order, order[1:]))),
    ]


def run_qaoa(
    instance,
    *,
    reps: int = 2,
    shots: int = 2048,
    maxiter: int = 120,
    restarts: int = 3,
    seed: int = 7,
    penalty: float = None,
    cvar_alpha: float = 0.25,
    runner=None,
    final_runner=None,
    final_shots: int = None,
    progress=None,
) -> QaoaResult:
    """Run the full TSP -> QUBO -> Ising -> QAOA pipeline on `instance`.

    `runner` executes the optimization loop; `final_runner` (default: `runner`)
    executes one last sampling job with the optimized angles. Splitting them is
    what lets the angles be trained on the simulator and only the final circuit
    be sent to IBM hardware.
    """
    if runner is None:
        from .backends import SimulatorRunner
        runner = SimulatorRunner(seed=seed)
    if final_runner is None:
        final_runner = runner
    if final_shots is None:
        final_shots = shots

    started_at = time.perf_counter()

    # --- TSP -> QUBO -> Ising --------------------------------------------
    qubo, encoding, penalty = build_tsp_qubo(instance, penalty=penalty)
    hamiltonian, _constant = qubo_to_ising(qubo)

    scale = max((abs(complex(c).real) for c in hamiltonian.coeffs), default=1.0)
    scale = scale or 1.0
    # `qaoa_ansatz` (the function) replaces the QAOAAnsatz class, which is
    # deprecated in Qiskit 2.1 and removed in 3.0.
    ansatz = qaoa_ansatz(hamiltonian * (1.0 / scale), reps=reps)

    circuit = ansatz.copy()
    circuit.measure_all()
    loop_circuit = runner.prepare(circuit)

    # --- the classical optimization loop ----------------------------------
    search = _TourSearch(instance, qubo, encoding)
    rng = np.random.default_rng(seed)
    evaluations = 0

    def objective(params) -> float:
        nonlocal evaluations
        evaluations += 1
        counts = runner.sample(loop_circuit, np.asarray(params, dtype=float), shots)
        scored = search.absorb(counts)
        value = _cvar(scored, cvar_alpha)
        if progress is not None:
            progress(evaluations, value, search.best_distance)
        return value

    best_params = None
    best_value = float("inf")
    for _ in range(max(1, restarts)):
        start_params = rng.uniform(0.0, np.pi, ansatz.num_parameters)
        outcome = minimize(
            objective, start_params, method="COBYLA",
            options={"maxiter": maxiter},
        )
        if outcome.fun < best_value:
            best_value = float(outcome.fun)
            best_params = np.asarray(outcome.x, dtype=float)

    # --- one final sampling job with the tuned angles ---------------------
    final_circuit = (
        loop_circuit if final_runner is runner else final_runner.prepare(circuit)
    )
    search.absorb(final_runner.sample(final_circuit, best_params, final_shots))

    elapsed = time.perf_counter() - started_at

    order = search.best_order
    checks = validate_tour(instance, order)
    route = [instance.names[i] for i in order] if order else []

    return QaoaResult(
        route=route,
        total_distance_km=(search.best_distance if order else float("inf")),
        valid=all(passed for _, passed in checks),
        checks=checks,
        execution_time_s=elapsed,
        mode=final_runner.mode,
        backend_name=final_runner.backend_name,
        backend_description=final_runner.describe(),
        job_ids=list(getattr(final_runner, "job_ids", [])),
        job_status=getattr(final_runner, "last_status", None),
        num_qubits=ansatz.num_qubits,
        reps=reps,
        shots=shots,
        penalty=penalty,
        qubo_terms=qubo.num_terms,
        hamiltonian_terms=len(hamiltonian),
        evaluations=evaluations,
        circuit_runs=runner.calls + (0 if final_runner is runner else final_runner.calls),
        total_samples=search.total_samples,
        feasible_samples=search.feasible_samples,
        distinct_feasible_tours=len(search.seen_tours),
        best_qubo_energy=search.best_energy,
    )
