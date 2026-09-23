"""Phase 2 - Quantum QAOA solver for the same TSP Phase 1 solves classically.

The pipeline is TSP -> QUBO -> Ising Hamiltonian -> QAOA:

    instance.py   pick a small TSP instance out of the real CSV
    qubo.py       TSP -> QUBO (binary quadratic model)
    ising.py      QUBO -> Ising Hamiltonian (SparsePauliOp over Z operators)
    qaoa.py       Ising -> QAOA ansatz, optimize, decode, validate
    backends.py   where the circuits run: Aer simulator or IBM Quantum hardware
    reference.py  the Phase 1 Nearest Neighbour tour and the exact optimum,
                  over the identical instance, for comparison

Nothing in this package modifies Phase 1; it imports `phase1` read-only for the
dataset, the graph and the travel costs, so both solvers optimize exactly the
same cost function.

QAOA is an approximate (heuristic) optimizer. It carries no guarantee of finding
the globally optimal tour.
"""
