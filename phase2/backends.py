"""Where the QAOA circuits actually run.

Two execution modes, behind one small interface so `qaoa.py` does not care which
is in use:

    [ Simulator ]    Qiskit Aer, local, the default.
    [ IBM Quantum ]  qiskit-ibm-runtime against real hardware, opt-in.

Credentials
-----------
IBM credentials are read from environment variables only:

    IBM_QUANTUM_TOKEN      required (API key)
    IBM_QUANTUM_INSTANCE   optional (CRN / instance identifier)
    IBM_QUANTUM_CHANNEL    optional (default: ibm_quantum_platform)
    IBM_QUANTUM_BACKEND    optional (default: the least busy usable device)

A git-ignored `.env` in the project root is folded into the environment first
(see `credentials.py`); a real environment variable always wins over it.

Nothing here hardcodes a token, prints one, or writes one to disk. The token is
read straight into the runtime service and is never echoed back - not in the
summary, not in an error message, not in a log line.

API note (verified against the installed packages, not from memory): with
qiskit-ibm-runtime 0.49 the only channels accepted are `ibm_quantum_platform`,
`ibm_cloud` and `local`. The retired `ibm_quantum` channel is gone, and circuits
must be transpiled to the target backend's ISA before being submitted.
"""

from __future__ import annotations

import os

from qiskit import transpile

from .credentials import ENV_FILE, TOKEN_VAR, load_env_file


class BackendError(Exception):
    """The requested execution backend is unusable."""


def _counts_from_pub(pub_result) -> dict:
    """Pull the measurement counts out of a V2 primitive result."""
    fields = list(pub_result.data.keys())
    if not fields:
        raise BackendError("The sampler returned no measurement data.")
    return pub_result.data[fields[0]].get_counts()


class SimulatorRunner:
    """Local Qiskit Aer sampler. Fast enough to run the whole QAOA loop."""

    mode = "simulator"

    def __init__(self, seed: int = None):
        from qiskit_aer import AerSimulator
        from qiskit_aer.primitives import SamplerV2

        self._simulator = AerSimulator()
        self._sampler = SamplerV2(seed=seed)
        self.backend_name = "aer_simulator"
        self.job_ids = []
        self.last_status = None
        self.calls = 0

    def prepare(self, circuit):
        return transpile(circuit, self._simulator, optimization_level=1)

    def sample(self, circuit, params, shots: int) -> dict:
        job = self._sampler.run([(circuit, params)], shots=shots)
        self.calls += 1
        return _counts_from_pub(job.result()[0])

    def close(self) -> None:
        pass

    def describe(self) -> str:
        return "Qiskit Aer (local simulator)"


class IBMRunner:
    """Sampler backed by IBM Quantum hardware via qiskit-ibm-runtime."""

    mode = "ibm"

    def __init__(self, backend_name: str = None, optimization_level: int = 3,
                 use_session: bool = False):
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2, Session
        except ImportError as exc:      # pragma: no cover - install-time problem
            raise BackendError(
                "qiskit-ibm-runtime is not installed. "
                "Install it with: pip install qiskit-ibm-runtime"
            ) from exc

        # A git-ignored .env is folded into the environment first; a real
        # environment variable always wins over it.
        load_env_file()

        token = os.environ.get(TOKEN_VAR)
        if not token:
            raise BackendError(
                f"{TOKEN_VAR} is not set. Put your IBM Quantum API key in "
                f"{ENV_FILE} (git-ignored) or export it into the environment, "
                f"then try again. Check it with: "
                f"python run_phase2.py --check-ibm. "
                f"Phase 2 never hardcodes credentials."
            )

        channel = os.environ.get("IBM_QUANTUM_CHANNEL", "ibm_quantum_platform")
        instance = os.environ.get("IBM_QUANTUM_INSTANCE") or None
        wanted = backend_name or os.environ.get("IBM_QUANTUM_BACKEND") or None

        try:
            self._service = QiskitRuntimeService(
                channel=channel, token=token, instance=instance
            )
        except Exception as exc:
            raise BackendError(f"Could not reach IBM Quantum: {exc}") from exc

        try:
            if wanted:
                self._backend = self._service.backend(wanted)
            else:
                self._backend = self._service.least_busy(
                    operational=True, simulator=False
                )
        except Exception as exc:
            raise BackendError(f"Could not select an IBM backend: {exc}") from exc

        self.backend_name = self._backend.name
        self.num_qubits = getattr(self._backend, "num_qubits", None)

        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

        self._pass_manager = generate_preset_pass_manager(
            optimization_level=optimization_level, backend=self._backend
        )

        # A Session keeps the whole optimization loop in one reservation; a
        # single final job does not need one.
        self._session = Session(backend=self._backend) if use_session else None
        mode = self._session if self._session is not None else self._backend
        self._sampler = SamplerV2(mode=mode)

        self.job_ids = []
        self.last_status = None
        self.calls = 0

    def prepare(self, circuit):
        return self._pass_manager.run(circuit)

    def sample(self, circuit, params, shots: int) -> dict:
        job = self._sampler.run([(circuit, params)], shots=shots)
        self.job_ids.append(job.job_id())
        self.calls += 1
        result = job.result()
        try:
            self.last_status = str(job.status())
        except Exception:               # status is informational only
            self.last_status = "DONE"
        return _counts_from_pub(result[0])

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass

    def describe(self) -> str:
        qubits = f", {self.num_qubits} qubits" if self.num_qubits else ""
        return f"IBM Quantum hardware: {self.backend_name}{qubits}"


def make_runner(mode: str, seed: int = None, backend_name: str = None,
                use_session: bool = False):
    """Build the runner for `mode` ('simulator' or 'ibm')."""
    if mode == "simulator":
        return SimulatorRunner(seed=seed)
    if mode == "ibm":
        return IBMRunner(backend_name=backend_name, use_session=use_session)
    raise BackendError(f"Unknown execution mode '{mode}'.")
