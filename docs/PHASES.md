# Phase log

Each phase stops for confirmation before the next one begins.

## Phase 0 — Project structure (complete)

- New, clean project folder, independent of any earlier implementation.
- `backend/` FastAPI skeleton: app factory, CORS, `/`, `/health`, `/dataset/status`.
- `backend/app/core/config.py` resolves the dataset path from settings.
- Empty packages reserved for later phases: `dataio`, `solvers`, `services`, `schemas`.
- `data/` created and waiting for `transmission_lines.csv`.
- Tests: `backend/tests/test_health.py`.

Not implemented: classical TSP, QAOA, IBM Quantum, frontend, auth, database,
energy-loss calculation.

### Environment note

The venv is built on **Python 3.13** (`py -3.13`). Python 3.14 is installed on this
machine and is the default `python`, but pydantic-core has no cp314 Windows wheel,
so pip tries a Rust build that fails without MSVC build tools. Qiskit also does not
publish 3.14 wheels yet, so 3.13 is the version to use for every later phase.

Verified at the end of Phase 0: `pytest -q` -> 3 passed.

## Phase 2 — Quantum QAOA (complete)

Solves the same TSP, on the same CSV, with the same `Distance_km` cost as the
Phase 1 Nearest Neighbour solver. Phase 1 was not modified; `phase2/` imports
`phase1` read-only for the dataset, the graph and the travel costs.

Pipeline, one module per step:

- `instance.py` — picks `k` stations from the real CSV (default: the 4 nearest
  the start by travel cost) and builds the cost matrix from
  `Network.travel_cost`. Nothing is fabricated.
- `qubo.py` — TSP -> QUBO. Position encoding `x[i][t]`, start pinned to
  position 0, so `(k-1)^2` binary variables. "Exactly one" constraints enter as
  squared penalties weighted `k * longest leg`.
- `ising.py` — QUBO -> Ising, by `x = (1 - z)/2`. Returns a `SparsePauliOp` of
  Z and ZZ terms plus a constant shift kept out of the circuit.
- `qaoa.py` — Ising -> QAOA. `qaoa_ansatz` (the function; the `QAOAAnsatz`
  class is deprecated in Qiskit 2.1), COBYLA over the 2p angles against a CVaR
  objective, every sampled bitstring decoded and every valid tour scored.
- `backends.py` — Aer simulator (default) or IBM Quantum runtime.
- `reference.py` — Phase 1 NN and the brute-force optimum on the same instance.

The Hamiltonian handed to the circuit is divided by its largest coefficient:
kilometre-scale coefficients would otherwise force unusably small gamma angles.
Reported distances always come from the unscaled instance.

QAOA is described throughout as approximate. No optimality claim is made; the
brute-force optimum is printed alongside so the gap is visible.

### Environment note

Installed into the Phase 1 venv: qiskit 2.5.2, qiskit-aer 0.17.2,
qiskit-ibm-runtime 0.49.0 (scipy and numpy come along as dependencies).

API points verified against the installed packages rather than assumed:

- `qiskit_ibm_runtime` 0.49 accepts only the `ibm_quantum_platform`, `ibm_cloud`
  and `local` channels — the old `ibm_quantum` channel is gone.
- Circuits must be transpiled to the target backend's ISA (via
  `generate_preset_pass_manager`) before submission to hardware.
- V2 primitives: `sampler.run([(circuit, params)], shots=n)`, results read as
  `result[0].data[<register>].get_counts()`.
- The console here is cp1252, so all Phase 2 output is ASCII.

### Not implemented in this phase

Frontend, authentication, database, energy-loss calculation, new datasets, and
any change to Phase 1's Dijkstra/graph code.

### Verified at the end of Phase 2

`python -m unittest discover -s tests` -> 58 tests, OK (31 Phase 1 + 27
Phase 2), with `-W error::DeprecationWarning` clean.

IBM Quantum mode is implemented and fails cleanly with a clear message when
`IBM_QUANTUM_TOKEN` is absent, but it has **not** been exercised against real
hardware — no credentials were available in this environment.

### Scope clarification (full network vs. QAOA subset)

The dataset is used in full and is never edited. All 26 stations and 38
transmission lines are loaded and connected as one network, and Phase 1 solves
that whole network classically (3,017.795 km from Mysuru Substation).

Phase 2 runs QAOA over a subset of that same network. The reason is the
encoding, not the data: the standard position-encoded TSP QUBO needs one binary
variable, and so one qubit, per (station, tour position) pair - O(n^2) growth.
With the start pinned to position 0 that is (n-1)^2 qubits, so the full network
would need (26-1)^2 = 625 qubits: not simulable on Aer, and beyond any device
available today.

The subset stations are selected directly from the real full CSV, by travel cost
from the start (or explicitly with --stations). No station is invented,
duplicated, renamed or merged, and the cost function is identical to Phase 1's.

A QAOA run solves the k-station tour it was given. It does not solve the full
26-station network, and every Phase 2 run says so explicitly, printing "k of 26
stations" and the 625-qubit figure the full network would require.

Tests covering this: `TestFullDatasetIsPreserved` in `tests/test_phase2.py`
asserts the network is still 26/38 after Phase 2 runs, that Phase 1 still tours
all 26 stations, that building an instance does not mutate the network, that no
station is duplicated or invented, that qubit growth really is (n-1)^2, and that
the printed scope note claims no more than it should.


## Phase 2b - full-network classical vs hybrid quantum (complete)

Phase 2 is not finished at the single-instance QAOA run: the headline comparison
has to be full network against full network. That is what `--full` produces.

### Why a hybrid at all

The resource analysis (previous section) rules out encoding the whole network
directly: 625 qubits and ~29,400 ZZ couplings, i.e. >=58,800 CNOTs for one QAOA
layer. Separately, the raw 38-line graph has NO Hamiltonian cycle - Bellary
Thermal Power Station is a cut vertex whose removal splits the network into a
22-station and a 3-station component - so an edge-based QUBO over the real lines
is infeasible by construction, not merely large. Phase 1 already handles this
correctly by solving TSP on the shortest-path (metric) closure, and Phase 2 uses
the same closure.

### The hybrid loop (phase2/hybrid.py)

1. Start from the complete Phase 1 Nearest Neighbour tour (all 26 stations).
2. Slide a window of W consecutive stations along the tour, pinning the station
   before and after it.
3. Hand the window to QAOA as an open path-TSP subproblem on W^2 qubits
   (phase2.qubo.build_path_qubo -> Ising -> qaoa_ansatz -> COBYLA/CVaR).
4. Accept the ordering when it shortens the tour.
5. Sweep until a sweep improves nothing.

Every intermediate state is a complete, valid 26-station tour.

### Result (W=4, 16 qubits per subproblem, Aer simulator)

    Classical Nearest Neighbour : 3,017.795 km   (0.607 ms)
    Hybrid QAOA                 : 2,851.243 km   (165.6 s)
    Improvement                 : +166.552 km    (5.52%)
    52 QAOA subproblems over 2 sweeps, 5 improvements accepted

### Honest framing, enforced in the output

- QAOA is the optimization engine inside a classical loop. The subproblems do
  not independently solve the 26-station TSP; window selection and acceptance
  are classical.
- No quantum advantage is claimed. Unrestricted classical 2-opt reaches
  2,083.565 km on this network - better than the hybrid. The binding constraint
  is the window neighbourhood, not the quantum optimizer: at W=4 the hybrid
  reaches exactly the tour an exhaustive brute-force subsolver finds over the
  same windows, so QAOA is solving its subproblems optimally.
- Every run prints these points; `print_full_framing` is not optional.

### Validation before anything is drawn

`validate_full_tour` checks both tours for: all 26 stations present and none
invented, 26 unique stations, starts at the requested station, returns to it,
every leg backed by a real transmission-line path with finite cost, and the
reported total matching a recomputed route length. `same_problem_checks` then
confirms both solvers were given the identical station set, start, cost function
and closure. The maps are written only if every check passes.

### Visualization

`phase2/visualize.py` reuses `phase1.visualize.plot_route` rather than
duplicating the renderer, so both maps keep Phase 1's geographic, overlap-free
layout and the hollow rings marking true coordinates. `phase1.layout` is
deterministic, so both maps share identical station coordinates and the routes
are visually comparable.

One additive change was made to Phase 1 for this: `plot_route` gained a
`route_label` keyword argument. It defaults to the existing Nearest Neighbour
wording, so Phase 1 renders exactly as before, and Phase 2 passes its own text
so a hybrid-QAOA map is never labelled a Nearest Neighbour route. Verified: a
fresh Phase 1 render differs from an older one only in the milliseconds printed
in the auto-generated title.

Outputs: `outputs/nn_full_route.png`, `outputs/qaoa_full_route.png`,
`outputs/nn_vs_qaoa_comparison.png`.

### Verified at the end of Phase 2b

`python -m unittest discover -s tests` -> 90 tests, OK, clean under
`-W error::DeprecationWarning`. No IBM hardware job was submitted.

### Don't-look bits (added for W=5)

At W=5 each subproblem is a 25-qubit circuit costing roughly a minute to
simulate, and the search needs 6 sweeps to converge, so full sweeps would be
~156 subproblems / ~2.7 hours. `hybrid_solve(prune=True)` (the default) applies
the standard local-search optimisation: a window whose seven stations - the five
free ones plus both fixed ends - are all unchanged since it last failed to
improve cannot improve now, so it is skipped. An accepted move marks its seven
stations dirty again.

Verified with the deterministic exact subsolver before being trusted:

    full sweeps  : 2,386.004 km  (156 subproblem solves)
    with pruning : 2,386.004 km  ( 85 subproblem solves)   45.5% less work

`--no-prune` disables it. `TestPruningPreservesResults` covers both the pruning
rule (deterministically, against full sweeps) and the fact that a pruned hybrid
run still produces a fully valid 26-station tour.

### Why W=5 needs more shots than W=4

The feasible subspace shrinks fast. At W=4, 24 of 65,536 bitstrings are valid
orderings (3.7e-4); at W=5 it is 120 of 33,554,432 (3.6e-6) - about 100x rarer.
512 shots per evaluation is enough at W=4 but not at W=5. Measured on three
sample windows:

    shots=2048, maxiter=15 -> 2 of 3 windows hit the exact optimum
    shots=4096, maxiter=15 -> 3 of 3 windows hit the exact optimum

So the W=5 runs use `--shots 4096`.


## Phase 2 final configuration (complete)

One command runs everything:

    python run_phase2.py

It loads the full 26-station network, lists the stations and asks which to start
from, solves the network classically (Phase 1 Nearest Neighbour), solves it again
with the hybrid QAOA reoptimizer on the local simulator, validates both
26-station tours, prints both routes with the comparison, and writes the three
maps. `--subset` selects the separate single-instance QAOA mode, which is what
`--mode ibm` sends to hardware; nothing contacts IBM by default.

### Default QAOA configuration and why

    window W=4  -> 16 qubits per subproblem
    depth p=2, 2048 shots, COBYLA maxiter 20 x 1 restart, CVaR alpha 0.25
    up to 8 sweeps (converges in 2), don't-look-bits pruning on

W=4 rather than W=5. W=5 (25 qubits) reaches a shorter tour - 2,386.004 km by
exact subsolver, 20.94% under NN - but each 25-qubit subproblem costs about a
minute of statevector simulation, so the full workflow ran ~90 minutes. That is
not a practical default. matrix_product_state was measured as an alternative and
is worse, not better: a single 25-qubit QAOA circuit did not finish in 10
minutes, because these circuits are too entangled for a tensor-network method.
W=5 remains available with `--window 5 --hybrid-shots 4096`.

### Measured result (W=4, Aer simulator)

    Classical Nearest Neighbour : 3,017.795 km   (1.2 ms)
    Hybrid QAOA (full 26)       : 2,851.243 km   (89.4 s)
    Difference                  : +166.552 km absolute, +5.52% relative
    49 QAOA subproblems over 2 sweeps, 5 accepted, 3 windows skipped
    Total wall time: ~90 seconds

2,851.243 km is exactly the tour an exhaustive brute-force subsolver reaches over
the same W=4 windows, so QAOA solved its subproblems optimally; the limit is the
window neighbourhood, not the quantum optimizer.

### Verified at the end of Phase 2

`python -m unittest discover -s tests` -> 100 tests, OK, clean under
`-W error::DeprecationWarning`. No IBM hardware job has been submitted at any
point in Phase 2.
