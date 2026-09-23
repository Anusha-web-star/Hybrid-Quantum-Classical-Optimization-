"""Step 2 of the pipeline: QUBO -> Ising Hamiltonian.

QAOA needs a Hamiltonian whose ground state is the answer. The QUBO uses binary
variables x in {0, 1}; a Hamiltonian uses spins z in {+1, -1}, the eigenvalues of
the Pauli Z operator. The standard change of variable is

    x_v = (1 - z_v) / 2

Substituting into  E(x) = sum_v h_v x_v + sum_{v<w} J_vw x_v x_w + offset  and
using  x_v x_w = (1 - z_v - z_w + z_v z_w) / 4  gives

    identity  :  offset + sum_v h_v / 2 + sum_{v<w} J_vw / 4
    Z_v       :  -h_v / 2 - sum_{w != v} J_vw / 4
    Z_v Z_w   :  J_vw / 4

The identity term is a constant energy shift. It is returned separately rather
than put in the circuit, where it would only add an unobservable global phase.
"""

from __future__ import annotations

from qiskit.quantum_info import SparsePauliOp


def qubo_to_ising(qubo):
    """QUBO -> (SparsePauliOp without identity, constant energy shift).

    `SparsePauliOp` labels are little-endian: the rightmost character is qubit 0.
    """
    n = qubo.num_vars
    constant = qubo.offset
    z_coeff = {}
    zz_coeff = {}

    for v, h in qubo.linear.items():
        constant += h / 2.0
        z_coeff[v] = z_coeff.get(v, 0.0) - h / 2.0

    for (v, w), j in qubo.quadratic.items():
        constant += j / 4.0
        z_coeff[v] = z_coeff.get(v, 0.0) - j / 4.0
        z_coeff[w] = z_coeff.get(w, 0.0) - j / 4.0
        zz_coeff[(v, w)] = zz_coeff.get((v, w), 0.0) + j / 4.0

    terms = []
    for v, coeff in sorted(z_coeff.items()):
        if coeff:
            terms.append((_label(n, [v]), coeff))
    for (v, w), coeff in sorted(zz_coeff.items()):
        if coeff:
            terms.append((_label(n, [v, w]), coeff))

    if not terms:                       # a degenerate instance with no couplings
        terms = [("I" * n, 0.0)]

    return SparsePauliOp.from_list(terms), constant


def _label(num_qubits: int, qubits: list) -> str:
    """Pauli label with Z on `qubits` and identity elsewhere, little-endian."""
    chars = ["I"] * num_qubits
    for q in qubits:
        chars[num_qubits - 1 - q] = "Z"
    return "".join(chars)
