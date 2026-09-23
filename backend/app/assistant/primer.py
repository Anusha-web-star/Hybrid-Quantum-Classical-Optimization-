"""The project primer: one written answer per thing GRIDOPT has to explain.

WHY THIS EXISTS
---------------
The dataset records answer "what is the loss on this line". The documents answer
"what does the methodology say". The source code answers "what does the program
actually do". None of them answer, in the words a person asks them:

    "What is RAG?"  "Why BM25 instead of embeddings?"  "Why 625 qubits?"
    "Why did QAOA pick this route over NN?"  "Did you achieve quantum advantage?"

Those are answerable from this project - every fact below is read off the code
and the documents in this repository - but they were not retrievable, because
nothing in the corpus was phrased the way the question is. Retrieval here is
lexical (BM25, see `retrieval.py`), so a chunk that never uses the word
"embeddings" cannot be found by a question about embeddings, however relevant it
is.

So each entry below is a short, self-contained explanation written in the
vocabulary of the question it answers, and pointed by `locator` at the file that
is the real authority for it. Nothing here is invented and nothing here is a
second source of truth: where a number could drift - the tariff, the station
count, the QAOA defaults - it is imported from the module that owns it rather
than typed in again.

WHAT BELONGS HERE, AND WHAT DOES NOT
------------------------------------
Belongs: an explanation of something this project does, does not do, or chose
not to do, that a reader would ask about in plain words.

Does not belong: any figure produced by a run (that is `runcontext.py`, per
request), any dataset value (that is the CSV, via `sources.py`), and any claim
this project has not earned - there is no quantum-advantage claim here, and no
statement that a result is optimal.
"""

from __future__ import annotations

from energy_cost.tariff import (HOURS_PER_YEAR,
                                KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE)

from app.assistant.chunking import chunk_markdown
from app.assistant.documents import Chunk

#: Read from the settings module so a changed default cannot silently make this
#: text wrong. These are the shipped defaults for a full-depth run.
from app.core.config import Settings as _Settings

_D = _Settings.model_fields
_WINDOW = _D["qaoa_window"].default
_SWEEPS = _D["qaoa_sweeps"].default
_REPS = _D["qaoa_reps"].default
_SHOTS = _D["qaoa_shots"].default
_MAXITER = _D["qaoa_maxiter"].default
_CVAR = _D["qaoa_cvar"].default
_MODEL = _D["assistant_model"].default
_TOP_K = _D["assistant_top_k"].default
_NUM_CTX = _D["ollama_num_ctx"].default
_OLLAMA_HOST = _D["ollama_host"].default

_TARIFF = KARNATAKA_HT_INDUSTRIAL_ENERGY_CHARGE

#: Station and line counts are NOT hardcoded here - they come from the dataset
#: at index time, through `network_summary_chunk` in `sources.py`. Where this
#: text has to refer to the scale of the problem it says "26 stations" because
#: that is the size the 625-qubit analysis was done at, and the analysis is
#: about that size specifically.
_N = 26

#: Every entry: (slug, title, locator, body). The locator names the file that is
#: the actual authority for the explanation, so a citation sends the reader to
#: the code or the document, not back to this file.
ENTRIES: tuple = (

    # ----------------------------------------------------------------- A ---
    ("purpose",
     "What GRIDOPT is and what it sets out to do",
     "README.md / phase1/main.py / phase2/main.py - project purpose",
     f"""WHAT GRIDOPT IS.
GRIDOPT is this project's name for a grid-optimization study: GRID + OPTimization.
It is a hybrid quantum-classical Travelling Salesman Problem (TSP) study over a
Karnataka electricity transmission network of {_N} stations joined by transmission
lines recorded in the project's CSV dataset.

THE OBJECTIVE.
Given a starting station, find a short closed route that visits every station in
the network exactly once and returns to the start. The route is then evaluated
for what it implies about transmission energy loss and what that loss is worth
in rupees.

TWO SOLVERS, ONE PROBLEM.
  1. Classical: Nearest Neighbour (phase1/nn_tsp.py).
  2. Hybrid quantum-classical: QAOA used as the optimization engine inside a
     classical reoptimization loop that starts from the Nearest Neighbour tour
     (phase2/hybrid.py).
Both minimise the same quantity - total route distance in Distance_km - over the
same graph, from the same starting station, so the comparison is like for like.

WHY TSP.
A tour that visits every station once and returns to the start is the standard
formulation for an inspection, maintenance or patrol circuit over a network, and
it is the canonical NP-hard combinatorial problem that QAOA is formulated for.
It gives a well-defined objective (total distance) over the project's real
network, which is what makes a classical baseline and a quantum-assisted method
comparable at all.

WHAT IS BEING OPTIMIZED: route distance (Distance_km), and nothing else.
WHAT IS NOT BEING OPTIMIZED: energy loss, loss percentage, monetary cost, power
flow, voltage, reliability or capacity. Those are EVALUATED after a route is
chosen; they never enter the optimization cost."""),

    # ----------------------------------------------------------------- B ---
    ("dataset",
     "The dataset: columns, provenance and limitations",
     "DATASET.md / data/README.md / phase1/data_loader.py - dataset definition",
     f"""THE DATASET.
One CSV in data/, read by phase1/data_loader.py. It records a Karnataka
transmission network: {_N} stations and the transmission lines between them (38
rows in the file). The network summary record in this knowledge base carries the
live counts read from the file itself.

COLUMNS.
  - Source / Destination: the two stations a line joins. Station coordinates
    (Latitude, Longitude) are recorded per station and are used for drawing the
    map and for nothing else - no distance is computed from them.
  - Type: the facility type of the source station (substation, power house,
    nuclear/thermal station, and so on).
  - Distance_km: the length of the line. THIS IS THE TSP COST. Every distance
    the solvers minimise is a sum of these.
  - Voltage_kV: the line's operating voltage (66 kV to 400 kV in this dataset).
  - Capacity_MW: the line's rated carrying capacity.
  - Loss_Percent: the modeled percentage of power lost on the line.
  - Energy_Loss_MW: the modeled power dissipated by the line.
  - Loss_Cost_Per_Hour_INR and Loss_Cost_Per_Year_INR: DERIVED by this project
    from Energy_Loss_MW and the published tariff (energy_cost/recompute.py).

SOURCE COLUMNS VERSUS DERIVED COLUMNS.
Distance_km, Voltage_kV, Capacity_MW, Loss_Percent and Energy_Loss_MW arrived
with the dataset and are read, never recomputed. The two rupee columns are the
only ones this project calculated.

LIMITATIONS, STATED PLAINLY.
  - The electrical values are MODELED, not metered. The dataset carries no
    measurement provenance, no load factor, no generation schedule and no outage
    profile.
  - It is a static snapshot: no time series, no demand curve, no seasonality.
  - It is a reduced network, not the whole Karnataka grid.
  - Some optional attributes are missing on some rows; the loader reports the
    per-column coverage rather than filling gaps, and nothing is estimated in
    place of a missing value."""),

    # ----------------------------------------------------------------- C ---
    ("graph-model",
     "The graph model: nodes, edges, Dijkstra and why one leg can be several lines",
     "phase1/network.py - Network, travel_cost, travel_path",
     """THE GRAPH.
phase1/network.py turns the dataset into an undirected weighted graph:
  - node  = a station
  - edge  = a transmission line
  - weight = that line's Distance_km
Parallel lines between the same pair are collapsed to the shorter one.

THE PROBLEM: THE GRAPH IS SPARSE.
26 stations joined by 38 lines means most station pairs have NO direct line. A
tour that must visit every station therefore cannot be built from direct lines
alone, and a TSP solver needs a cost between every pair of stations.

THE FIX: SHORTEST-PATH CLOSURE (DIJKSTRA).
travel_cost(a, b) is the length of the shortest CHAIN of real transmission lines
from a to b, computed with Dijkstra over Distance_km. travel_path(a, b) returns
the stations along that chain. So:
  - every cost the solvers see is a sum of real line lengths;
  - no straight-line "as the crow flies" distance is ever substituted;
  - nothing is invented for a missing line.

WHY DIJKSTRA AND NOT SOMETHING ELSE.
All weights are positive distances, the graph is tiny, and Dijkstra is exact for
this case. There is no negative weight to need Bellman-Ford and no heuristic
worth an A* on 26 nodes.

CONSEQUENCE: A TOUR LEG IS NOT A TRANSMISSION LINE.
One leg of the tour - "station X to station Y" - may physically traverse several
lines, passing through intermediate stations that are not counted as visited at
that point. Each Leg records that chain in leg.path, and leg.is_direct says
whether a single line joins the two. This is exactly why the energy analysis
walks leg.path pair by pair instead of treating a leg as one line."""),

    # ----------------------------------------------------------------- D ---
    ("nearest-neighbour",
     "The classical solver: Nearest Neighbour, and what it cannot do",
     "phase1/nn_tsp.py - solve()",
     """NEAREST NEIGHBOUR (NN), the classical baseline.
The algorithm, exactly as phase1/nn_tsp.py implements it:
  1. Start at the station the user chose. resolve_station() maps what the user
     typed to a real station name, and refuses an ambiguous match rather than
     guessing.
  2. Before timing anything, check every station is reachable from the start; if
     the network is disconnected, fail with an explanation instead of returning
     a partial tour.
  3. From the current station, move to the NEAREST station not yet visited,
     where "nearest" is Network.travel_cost - the Dijkstra shortest-path cost.
     Ties are broken by station name, so the same dataset and the same start
     always produce the same tour.
  4. Repeat until every station has been visited exactly once.
  5. Close the tour by returning from the last station to the start.
The result records every leg, the total distance, the execution time and the
number of legs that used a direct line.

COMPLEXITY: O(n^2) over the station count. It runs in milliseconds.

WHY NEAREST NEIGHBOUR.
It is the standard greedy construction heuristic for TSP: simple, deterministic,
fast, and a fair, well-understood baseline. The hybrid solver also needs a
complete starting tour to improve, and NN supplies it.

ITS LIMITATIONS, WHICH ARE THE POINT OF HAVING A SECOND SOLVER.
  - It is a heuristic with NO optimality guarantee.
  - It is greedy and myopic: each step takes the locally cheapest hop and never
    reconsiders it.
  - It characteristically strands far stations for the end, so the closing legs
    can be long.
  - The tour it produces depends on the starting station."""),

    # ----------------------------------------------------------------- E ---
    ("qaoa",
     "What QAOA is, and how it is set up in this project",
     "phase2/qaoa.py / phase2/qubo.py / phase2/ising.py - the quantum pipeline",
     f"""QAOA = Quantum Approximate Optimization Algorithm.
A variational, hybrid algorithm for combinatorial optimization. The pipeline in
this project, file by file:

  1. phase2/qubo.py - the problem becomes a QUBO (Quadratic Unconstrained Binary
     Optimization). Position encoding: binary variable x[i][t] is 1 when station
     i occupies position t of the tour. The starting station is pinned to
     position 0. QUBO has no constraints, so "each station gets exactly one
     position" and "each position holds exactly one station" are added as
     squared penalties with weight A, chosen large enough that violating a
     constraint always costs more than any distance it could save.
  2. phase2/ising.py - the QUBO is mapped to an Ising cost Hamiltonian, a
     SparsePauliOp of Z and ZZ terms.
  3. phase2/qaoa.py - QAOA prepares the state
       |psi(beta,gamma)> = prod_l exp(-i beta_l H_mixer) exp(-i gamma_l H_cost) |+>^n
     with p layers ("reps"), a classical optimizer (COBYLA, from SciPy) tuning
     the 2p angles. Each evaluation samples the circuit, every sampled bitstring
     is decoded back into a station ordering, orderings that are genuine
     permutations are scored with the REAL Distance_km costs, and the best valid
     one seen is kept.

THE OBJECTIVE IS CVaR, NOT THE MEAN.
The angles are tuned against the Conditional Value at Risk of the sampled energy
distribution (best alpha = {_CVAR} fraction), which optimises the good tail of
samples rather than the average - the standard choice when what you want is the
best sample drawn, not a good average.

SCALING NOTE.
The Ising coefficients carry kilometre magnitudes, which would force absurdly
small gamma angles, so the Hamiltonian handed to the circuit is divided by its
largest coefficient. That rescales angles only; every reported distance comes
from the unscaled instance.

DEFAULT PARAMETERS for a full-depth run (backend/app/core/config.py):
  window W = {_WINDOW}, sweeps = {_SWEEPS}, reps p = {_REPS}, shots = {_SHOTS},
  COBYLA maxiter = {_MAXITER}, CVaR alpha = {_CVAR}.

WHAT QAOA IS NOT, HERE.
Approximate and heuristic. It gives no guarantee of finding the optimal tour;
the answer is the best VALID tour it happened to measure, which is why every
tour is validated before it is reported."""),

    # ----------------------------------------------------------------- E ---
    ("625-qubits",
     "Why a 26-station TSP needs 625 qubits, and why that cannot be run directly",
     "phase2/qubo.py (position encoding) / phase2/hybrid.py (module docstring)",
     f"""WHY 625 QUBITS.
The position encoding needs one binary variable x[i][t] per (station, position)
pair, and one qubit per binary variable. Pinning the starting station to
position 0 leaves k-1 free stations and k-1 free positions, so a k-station tour
needs

    (k - 1)^2 qubits.

For the full network, k = {_N}:  ({_N} - 1)^2 = 25^2 = 625 qubits.
The coupling count grows with it: roughly 29,400 ZZ terms for that instance.

WHY IT CANNOT BE RUN DIRECTLY.
  - On a SIMULATOR: state-vector simulation of 625 qubits would need 2^625
    complex amplitudes. That is not a large number, it is an impossible one -
    far beyond the atoms available to store it. No classical machine runs it.
  - On REAL HARDWARE: devices with a few hundred physical qubits exist, but the
    usable width after error and connectivity constraints is far smaller, and a
    dense 29,400-coupling problem would need enormous SWAP overhead and circuit
    depth well past current coherence times.
So a direct full-network QAOA is not a thing this project declined to do for
convenience; it is not executable anywhere today.

WHAT IS DONE INSTEAD.
The problem is decomposed into windows of W consecutive stations, each needing
W^2 qubits - 16 qubits at the default W = {_WINDOW}, 9 at W = 3. That IS
simulable, and it is the same QAOA code running on each subproblem. See the
hybrid-algorithm entry for how the windows are chosen, solved and spliced back."""),

    # ----------------------------------------------------------------- F ---
    ("hybrid-algorithm",
     "How the hybrid QAOA algorithm actually works, step by step",
     "phase2/hybrid.py - hybrid_solve() and reoptimize_window()",
     f"""THE HYBRID ALGORITHM, exactly as phase2/hybrid.py implements it.

  1. START FROM A COMPLETE TOUR. The Nearest Neighbour tour over all {_N}
     stations is the starting point. Its length is recorded as
     start_distance_km.

  2. SLIDE A WINDOW. For each offset around the tour, take W consecutive
     stations as the FREE set, with the station before the window (entry) and
     the station after it (exit) held FIXED. The rest of the tour is untouched.

  3. FORMULATE THE SUBPROBLEM. reoptimize_window() builds the cost data for that
     window from the network's own travel_cost values - entry-to-each, each-to-
     exit, and every pair - then calls build_path_qubo() to write it as an open
     path-TSP QUBO: order the free stations between a fixed entry and a fixed
     exit. The penalty weight is set from the largest distance involved, so
     breaking a constraint always costs more than any distance it could save.

  4. RUN QAOA. solve_qubo_qaoa() maps the QUBO to an Ising Hamiltonian, builds
     the QAOA ansatz, and lets COBYLA tune the angles against the CVaR
     objective, sampling the circuit each evaluation.

  5. DECODE THE CANDIDATE. Each sampled bitstring is decoded back into an
     ordering of the free stations. A bitstring that is not a valid permutation
     is discarded, not repaired.

  6. SPLICE AND EVALUATE. A decoded ordering is scored as the real segment
     length entry -> ordering -> exit, using the same Distance_km costs.

  7. ACCEPT ONLY IF IT IMPROVES. The new ordering replaces the old one only when
     its segment is strictly shorter than the current segment (with a 1e-9
     tolerance). Otherwise the tour is left exactly as it was. Because entry and
     exit are fixed and the free stations are just reordered among their own
     slots, a shorter segment means a shorter TOTAL tour - every intermediate
     state is a complete, valid {_N}-station tour.

  8. SWEEP. Repeat over every window position; that is one sweep. Sweeps repeat
     until a whole sweep accepts nothing, or the sweep cap ({_SWEEPS} by default)
     is reached.

  9. PRUNING (don't-look bits). A window whose stations are all unchanged since
     it last failed to improve cannot suddenly improve, so it is skipped and
     counted as subproblems_skipped. Verified against unpruned sweeps with an
     exact subsolver: same tour, about 45% fewer subproblems.

 10. REPORT. The final tour is rotated so the requested start is at the front,
     and validate_full_tour() checks that all stations are present, none
     repeated or invented, the tour starts and ends at the requested station,
     every leg has a real transmission-line path and a finite cost, and the
     reported total matches a recomputation.

WHAT IS CLASSICAL AND WHAT IS QUANTUM.
Classical: the starting tour, the choice of windows, the acceptance test, the
sweeping and the pruning. Quantum (simulated): solving each window subproblem.
The project makes no quantum-advantage claim."""),

    # ------------------------------------------------------------- F / 4 ---
    ("why-hybrid-route-differs",
     "Why the hybrid QAOA route differs from - and can be shorter than - the NN route",
     "phase2/hybrid.py - the acceptance test in hybrid_solve()",
     """WHY THE HYBRID ROUTE CAME OUT DIFFERENT FROM THE NEAREST NEIGHBOUR ROUTE.
This is answered by the implementation, not by any judgement made inside the
quantum circuit:

  1. The Nearest Neighbour tour is the baseline the hybrid run STARTS from.
  2. The loop takes a window of W consecutive stations of that tour, holding the
     station before and after the window fixed.
  3. QAOA searches orderings of those free stations and the sampled bitstrings
     are decoded into candidate orderings.
  4. A candidate is spliced back into the complete tour and the real segment
     length is recomputed with the project's own Distance_km costs.
  5. The candidate replaces the existing ordering ONLY IF the recomputed length
     is strictly shorter. Otherwise it is discarded and the tour is unchanged.
  6. This repeats window by window and sweep by sweep.

THEREFORE: the final hybrid route is the Nearest Neighbour route plus the
accepted changes, and every accepted change was accepted because it reduced
measured route distance. It can never be longer than the tour it started from.
Nearest Neighbour cannot make these changes itself: it is greedy and never
revisits a choice once made, so a reordering that only pays off across several
stations is invisible to it.

HOW TO SAY THIS CORRECTLY.
Say: "the reordering was accepted because it shortened the total route distance
when it was spliced back and re-measured."
Do NOT say: "QAOA understood that this route was better", "QAOA decided", or
"QAOA proved the route is optimal." QAOA samples bitstrings from a parameterised
circuit; the comparison, the acceptance and the final route are classical
arithmetic on real distances. The result is approximate and carries no
optimality claim.

The run's own numbers - which route was shorter, by how many km, how many
improvements were accepted - are in the attached run's comparison output. If no
run is attached, those specific figures are not available."""),

    # ----------------------------------------------------------------- E ---
    ("backends-hardware",
     "What hardware this runs on: Aer simulator, the IBM Quantum option, and no advantage claim",
     "phase2/backends.py - SimulatorRunner and the IBM runtime path",
     """WHERE THE CIRCUITS ACTUALLY RUN.

AER SIMULATOR - the default, and what every result in this project came from.
Qiskit Aer is IBM's local, classical simulator of quantum circuits. It runs on
this machine's CPU, needs no account, no token and no queue, and it is what the
API always uses: no endpoint can submit a job to real hardware. "Simulated"
means the quantum state is computed classically - the algorithm is genuine, the
quantum speed is not being measured.

IBM QUANTUM - available, opt-in, and not used for the reported results.
phase2/backends.py can run the same circuits on real IBM devices through
qiskit-ibm-runtime. Credentials are read from environment variables only
(IBM_QUANTUM_TOKEN and optional instance/channel/backend variables); nothing is
hardcoded, printed or logged. Circuits must be transpiled to the target
backend's ISA before submission.

WHAT WOULD CHANGE ON REAL HARDWARE.
Results would be noisier: decoherence, gate error and readout error all reduce
the fraction of sampled bitstrings that decode to a valid permutation. Runs
would also be slower in wall-clock terms because of queueing. The window size
would still be bounded by what the device can take. Nothing about the method
would change - the same QUBO, the same acceptance test.

QUANTUM ADVANTAGE: NOT CLAIMED, AND NOT DEMONSTRATED.
A shorter hybrid route is a route-distance difference on one instance produced
by a classical loop whose subproblems were solved by simulated QAOA on a
classical CPU. That is not evidence of quantum advantage, and this project does
not claim any. On this dataset a W=4 hybrid run reaches exactly the same tour as
an exhaustive brute-force subsolver over the same windows - so QAOA is solving
its subproblems well, and the limiting factor is the window neighbourhood, not
the quantum optimizer."""),

    # ----------------------------------------------------------------- G ---
    ("energy-loss",
     "Energy_Loss_MW, how a route is mapped to real lines, and why distance is not loss",
     "energy_cost/route_loss.py - the route-to-lines mapping",
     """WHAT Energy_Loss_MW MEANS.
It is the modeled POWER, in megawatts, that a transmission line dissipates while
it carries its modeled flow. It is a steady-state property of the LINE, not of a
trip across it. It is a source column of the dataset, read and never recomputed.

POWER VERSUS ENERGY.
MW is power - a rate. Energy is power held for a time: 1 MW for one hour is
1 MWh = 1000 kWh. That conversion is why an hourly cost can be quoted at all,
and it is the only place a time enters: the dataset has no time series.

HOW A ROUTE BECOMES A SET OF LINES (energy_cost/route_loss.py).
A tour leg is not a transmission line - on a sparse network one leg may traverse
several. So the mapping walks each leg's path pair by pair. Every consecutive
pair in a path IS a real line, because travel_path only ever steps along real
adjacency, and each step is looked up with Network.edge_between to read that
line's own Distance_km, Loss_Percent and Energy_Loss_MW. No value is recomputed
and none is invented. A step that matched no line would be reported as
unmatched, not costed as free.

WHY THE TOTAL SUMS DISTINCT LINES, NOT TRAVERSALS.
On a sparse network a tour often crosses the same line more than once. Because
Energy_Loss_MW is a continuous property of the line, adding it once per
traversal would count the same loss twice. The headline figure is therefore the
sum of Energy_Loss_MW over the SET of distinct lines the route touches. The
traversal-weighted sum is reported alongside it as traversal_energy_loss_mw, so
the difference is visible rather than hidden.

WHY DISTANCE DOES NOT DETERMINE LOSS.
Total km and total loss are two independent readings taken from the same set of
lines. Loss depends on each line's own modeled characteristics, not on how long
the route is. A SHORTER route can cross lossier lines and carry MORE modeled
loss than a longer one. Nothing in this project derives loss from length, and a
route that is N km shorter is never "N km less energy loss"."""),

    # ----------------------------------------------------------------- G ---
    ("money",
     "The rupee figures: Rs. 6.60/kWh, hourly cost, and why the annual number is so large",
     "energy_cost/tariff.py - the KERC rate and the cost functions",
     f"""WHERE THE RATE COMES FROM.
Rs. {_TARIFF.inr_per_kwh:.2f} per kWh ({_TARIFF.paise_per_kwh} paise/kWh) - the
HT-2(a) industrial ENERGY CHARGE approved by the Karnataka Electricity
Regulatory Commission in its Combined Tariff Order 2025, read from the
Commission's own order. It is not an assumption or a market estimate. HT-2(a) is
used because the dataset is a high-voltage transmission network, so energy lost
on it is HT-level energy.

THIS IS AN ENERGY CHARGE ONLY - it is the value of the lost energy, and it is
not an electricity bill. Annualized values assume continuous modeled operation.
Both of those must be said whenever a rupee figure from this project is quoted.
(This obligation is stated first on purpose: a chunk longer than the prompt's
per-chunk cap loses its END, so a caveat at the bottom is the first thing to be
cut - leaving the rupee figures behind without it.)

THE TWO CALCULATIONS, as this project defines them:
    Loss_Cost_Per_Hour_INR = Energy_Loss_MW x 1000 x {_TARIFF.inr_per_kwh:.2f}
    Loss_Cost_Per_Year_INR = Loss_Cost_Per_Hour_INR x {HOURS_PER_YEAR}
The factor 1000 converts MW held for one hour into kWh. {HOURS_PER_YEAR} is the
number of hours in a year.

WHY THE ANNUAL FIGURE IS SO LARGE - lakhs per hour becoming crores per year.
It is the multiplication by {HOURS_PER_YEAR} that does it, and nothing else. An
hourly figure in lakhs becomes a yearly figure in crores because a year has
{HOURS_PER_YEAR} hours: the scale reflects continuous operation over a year, not
a large loss per hour. (1 lakh = 100,000; 1 crore = 10,000,000.)

WHAT THE ANNUAL FIGURE IS NOT.
It is NOT an actual Karnataka electricity bill and NOT an actual annual loss. It
assumes the modeled loss is present for all {HOURS_PER_YEAR} hours - continuous
modeled operation - and the dataset carries no load factor, no generation
schedule and no outage profile to say otherwise. It is an estimate of what a
year at this constant modeled loss would be worth.

WHAT THE RATE EXCLUDES - it is an energy charge and nothing else:
{chr(10).join('  - ' + item for item in _TARIFF.excludes)}

A figure of Rs. 3.00/kWh circulates as the March 2025 KERC HT industrial energy
charge. It was checked against the order and not adopted: the FY2025-26 HT-2(a)
energy charge is {_TARIFF.paise_per_kwh} paise/kWh. Rs. 3.00/kWh is used nowhere
in this project."""),

    # ----------------------------------------------------------------- G ---
    ("energy-not-optimized",
     "Is GRIDOPT optimizing energy loss? No - and what that would take",
     "phase1/nn_tsp.py and phase2/hybrid.py (the cost they minimise) / DATASET.md",
     """ARE YOU OPTIMIZING ENERGY LOSS? NO.
This project's TSP objective is the route-distance objective: Distance_km, and
nothing else. Neither solver optimizes energy loss. That is visible in the code -
Nearest Neighbour picks the nearest unvisited station by travel_cost, and the
hybrid loop accepts a window reordering only when the recomputed segment
DISTANCE is shorter. Energy_Loss_MW, Loss_Percent and the rupee columns appear
nowhere in either objective.

WHAT IS DONE WITH ENERGY INSTEAD.
Energy loss is ANALYSED after the fact. Once a route exists, energy_cost/
route_loss.py maps it onto the physical lines it uses and sums Energy_Loss_MW
over the distinct lines, then prices that loss at the KERC energy charge. That
is an evaluation of a route the distance objective chose - not a target the
solver aimed at.

WHY NOT OPTIMIZE ENERGY LOSS?
Because it would be a different problem, and the project is explicit about not
pretending otherwise. An energy-aware optimization objective would require
energy-loss terms in the optimization cost itself - for TSP that means a second edge
weight, a chosen trade-off between km and MW (or a single monetised objective),
and a QUBO whose coefficients carry that combined cost. The dataset would also
be doing work it was not built for: Energy_Loss_MW is a steady-state property of
an energised line, so summing it along a visiting order is a proxy, not a model
of the energy a patrol actually causes.

THE HONEST CONSEQUENCE.
The hybrid route being shorter does NOT mean it loses less energy. It can use a
different set of lines and come out with higher modeled loss. The run's energy
block reports both routes' loss side by side precisely so that this is visible
rather than assumed."""),

    # ----------------------------------------------------------------- H ---
    ("backend",
     "The FastAPI backend: endpoints, what each does, and why FastAPI",
     "backend/app/main.py and backend/app/api/routes/ - the API surface",
     """THE BACKEND is a FastAPI application (backend/app/), created by
create_app() in backend/app/main.py. It imports the Phase 1 and Phase 2 solvers
directly and runs them in process; it holds no second copy of the network and no
database connection.

THE ENDPOINTS.
  GET  /health                 liveness. Public - the dashboard polls it for its
                               connection indicator before anyone signs in.
  GET  /                       service index: version, endpoints, execution mode.
  GET  /stations               every station in the dataset.
  POST /stations/resolve       check a starting station without running a solver.
  GET  /network                the network summary and every transmission line.
  POST /solve/classical        Phase 1 Nearest Neighbour. Answers in milliseconds.
  POST /solve/hybrid           the hybrid QAOA loop on the local Aer simulator.
  POST /solve/compare          both solvers, the comparison, the energy analysis
                               and the rendered figures - guaranteed to come from
                               the same network and the same start. This is what
                               the dashboard's Run Optimization button calls.
  GET  /graphs                 which figures exist.
  GET  /graphs/{name}          one rendered PNG (loaded by an <img> tag).
  POST /assistant/query        this assistant: a question in, a grounded answer
                               and its sources out.
  GET  /assistant/status       whether the knowledge base and a local model are
                               available.

REQUESTS, VALIDATION AND ERRORS.
Request and response shapes are Pydantic models in backend/app/schemas/. An
unknown or ambiguous starting station is a 422 with a structured body naming the
problem; a network that cannot support a tour is a 409; a missing dataset is a
503. Errors are structured objects ({"error": ..., "message": ...}), not bare
strings, so the frontend can act on the code rather than parse prose. The solver
handlers are plain `def`, so FastAPI runs them on its threadpool and a long
hybrid run does not block the event loop.

WHY FastAPI.
The solvers are Python, so the API had to be Python to call them in process.
FastAPI gives typed request/response validation from Pydantic models, automatic
OpenAPI docs at /docs, dependency injection for the auth gate, and the threadpool
behaviour above - with no server code to write."""),

    # ----------------------------------------------------------------- I ---
    ("frontend",
     "The React frontend: the dashboard, and what happens when you click Run Optimization",
     "frontend/src/App.jsx and frontend/src/hooks/useOptimization.js",
     """THE FRONTEND is a React application built with Vite (frontend/src/).

THE CONSOLE, once signed in (App.jsx): a rail across the top with the network
summary and connection status, then three columns - the control column (origin
station, run depth, run button, live log), the network canvas in the middle, and
the results column - over a drawer holding routes, energy, figures, methodology
and the assistant panel.

WHAT EACH PART SHOWS.
  - Network canvas: the stations and transmission lines drawn from /network,
    with the NN route, the hybrid route or both overlaid, plus route playback
    that animates a route leg by leg (useRoutePlayback.js).
  - Results column: both routes' distance, runtime and validity, and the
    improvement between them.
  - Energy panel: the per-route energy-loss and cost table from the run's energy
    block.
  - Figures panel: the PNGs rendered by the backend for this run.
  - Methodology panel: what was actually run - window, sweeps, qubits, backend.
  - Assistant panel: this assistant, with the current run attached.
UI states are explicit: loading, empty, error with a retry, and running.

WHAT HAPPENS WHEN THE USER CLICKS RUN OPTIMIZATION (useOptimization.js).
  1. The origin station and the depth profile are locked in and logged.
  2. POST /solve/classical runs first. It answers in milliseconds, so the
     Nearest Neighbour route appears immediately.
  3. POST /solve/compare then runs the hybrid QAOA loop with the profile's
     options (Preview: W=3, 1 sweep; Full depth: W=4, 8 sweeps). The backend is
     synchronous, so this call returns only when both solvers have finished.
  4. While it waits, the panel shows the real elapsed seconds - no fake progress
     percentage is invented, because the backend reports none.
  5. The response - both tours, the comparison, the energy analysis and the
     figures - becomes the run the whole dashboard renders, and the canvas
     switches to the comparison view.
  6. Re-running aborts any in-flight request; changing the origin clears the
     displayed run so the results and the drawn route always describe the same
     origin.

HOW THE FRONTEND TALKS TO THE BACKEND.
Over plain HTTP JSON. frontend/src/api/client.js is the only module that knows
about fetch, status codes and the API base URL; it normalises every error into
an ApiError. frontend/src/api/gridopt.js has one function per endpoint. No
solver logic, no distance and no comparison is computed in the browser.

WHY REACT.
The dashboard is stateful - a run in flight, a selected origin, a playback
position, a drawer tab - and component state with hooks keeps each of those in
one place. Vite gives a fast dev server and a static production build that any
host can serve."""),

    # ----------------------------------------------------------------- J ---
    ("database",
     "Supabase PostgreSQL: what is stored, the view, RLS, and why it is there",
     "supabase/schema.sql - tables, view and row-level security",
     """THE DATABASE is Supabase, which is hosted PostgreSQL with an HTTP data API
and auth service on top.

WHAT IS STORED (supabase/schema.sql):
  - stations: name, type, latitude, longitude.
  - transmission_lines: the two endpoint stations and the line's attributes.
  - an expanded VIEW that joins lines to their endpoint stations so a row reads
    as a complete record without a manual join.
Seeded FROM the CSV by supabase/generate_seed.py. The CSV remains the source of
truth: it is never written to, renamed or derived from the database, and every
statement in the schema is idempotent so re-applying it changes nothing.

ROW LEVEL SECURITY (RLS).
RLS is enabled on the tables and no policy grants the browser's anonymous key
read access, so a client holding only the publishable key gets nothing back from
the data API. The frontend reads network data through the FastAPI backend, not
through the Supabase data API.

WHY SUPABASE IS IN THE PROJECT AT ALL.
It gives the project a real, queryable relational mirror of the dataset - so the
network can be inspected with SQL, and so the work is not purely file-based -
without running a database server. The solvers deliberately do NOT depend on it:
they read the CSV through phase1/data_loader.py, so the optimization runs with
the database switched off entirely.

AUTHENTICATION, AS CURRENTLY IMPLEMENTED.
Sign-in is SUPABASE AUTH - the same Supabase project, its Authentication
service rather than its tables.
  - Register calls supabase.auth.signUp({ email, password, options: { data:
    { username } } }) from frontend/src/hooks/useAuth.js. The user row is
    created in Supabase Authentication -> Users, and the username is stored on
    it as user_metadata: a label, never a credential.
  - Login calls supabase.auth.signInWithPassword({ email, password }).
  - Logout calls supabase.auth.signOut().
  - The browser holds the session, not a password. The supabase-js client
    persists it, refreshes the access token before expiry, and reports
    SIGNED_IN, SIGNED_OUT and TOKEN_REFRESHED through onAuthStateChange, which
    is the single source of truth for whether anyone is signed in. GRIDOPT
    stores no password and keeps no account table of its own.
  - The browser holds only the project URL and the public anon/publishable key
    (frontend/src/lib/supabase.js). The service-role key is never in the
    frontend.
  - The API is a resource server for those tokens: frontend/src/api/client.js
    attaches the session's access token as `Authorization: Bearer <jwt>` on
    every request, and backend/app/core/auth.py verifies the ES256 signature
    against the project's published JWKS, plus audience, issuer and expiry,
    before any handler runs (AUTH_MODE=supabase, the default). AUTH_MODE=demo
    remains as an offline fallback that demands no token and is not a security
    boundary."""),

    # ----------------------------------------------------------------- K ---
    ("rag",
     "What RAG is, and how this assistant implements it",
     "backend/app/assistant/service.py - the retrieve, assemble, generate pipeline",
     f"""RAG = RETRIEVAL-AUGMENTED GENERATION.
The assistant does not answer from the model's own memory. It first RETRIEVES
the pieces of this project that are relevant to the question, then the language
model GENERATES an answer from those pieces only. Retrieval supplies the facts;
the model supplies the sentences.

THE PIPELINE IN THIS PROJECT (backend/app/assistant/service.py):
    question
      -> BM25 retrieval over the project index, plus the attached run
      -> top {_TOP_K} chunks
      -> assembled into a bounded, labelled context block
      -> a grounding system prompt + that context + the question
      -> local Ollama model generates the answer
      -> the answer is returned with the exact sources it read

WHY RAG WAS USED HERE.
  - Grounding: the answers must be about THIS project - its 26 stations, its
    dataset values, its run - none of which any pretrained model has ever seen.
  - Verifiability: every answer comes back with the sources that supported it, so
    a reader can check it against a CSV row or a file.
  - Freshness without retraining: re-running the reindex command picks up a
    changed CSV, document or source file immediately. Fine-tuning a model on the
    project would cost far more and still have to be redone on every change.
  - Honesty: when retrieval finds nothing, the assistant says the information is
    not available and returns grounded=false, instead of producing a fluent
    guess.

WHAT IS INDEXED: the transmission-line dataset, the project documentation
(DATASET.md, README.md, docs/PHASES.md, data/README.md), the approved tariff
reference, this curated project knowledge, and an allowlist of the project's own
SOURCE CODE. The attached run is retrieved per request and is never written into
the shared index."""),

    # ----------------------------------------------------------------- K ---
    ("bm25",
     "Why BM25 lexical retrieval instead of embeddings or a vector database",
     "backend/app/assistant/retrieval.py - Bm25Retriever and the coverage gate",
     f"""WHAT BM25 IS.
A lexical ranking function: it scores a chunk against a question by the
question's terms that appear in it, weighting rare terms more (IDF), saturating
repeated terms, and normalising for chunk length. It is the classic, well-tested
keyword ranker - the default in search engines such as Lucene/Elasticsearch.

WHY BM25 AND NOT EMBEDDINGS / A VECTOR DATABASE.
  1. The corpus is a few hundred short chunks, not millions. BM25 over it is
     microseconds in process, with no index server.
  2. The questions are dominated by EXACT tokens: station names, line pairs and
     column names like Energy_Loss_MW. Lexical matching is exact on precisely
     those, where an embedding is approximate.
  3. Embeddings have to come from somewhere. Generation here is deliberately a
     LOCAL model so nothing leaves the machine and nothing is billed; adding a
     cloud embedding vendor would undo both at once, and a second resident local
     model is real weight to serve a few hundred chunks.
  4. pgvector was considered and rejected for this setup: the backend has no
     database connectivity at all - it reads the CSV - so reaching pgvector would
     mean adding a Postgres driver and a remote migration for no measurable gain.
  5. Determinism: the same question retrieves the same chunks every time, which
     is what makes the assistant's behaviour testable.

THE DOOR IS LEFT OPEN. `Retriever` is a Protocol, and Bm25Retriever is one
implementation of it. A vector retriever can replace it without touching the
service, the endpoint or the frontend.

THE COVERAGE GATE - how an off-topic question gets nothing.
A raw score threshold cannot separate on-topic from off-topic, because BM25
scores are unnormalised: one incidental rare word can out-score a real match. So
a chunk qualifies only if it matches at least a fixed fraction of the question's
distinctive terms. A question the project has nothing to say about retrieves
zero chunks, and the assistant returns its unavailable line with grounded=false
instead of guessing."""),

    # ----------------------------------------------------------------- K ---
    ("ollama",
     "Why Ollama and llama3.2:3b, and why no ChatGPT or Claude API is required",
     "backend/app/assistant/llm.py - the loopback-only local model call",
     f"""WHAT OLLAMA IS.
A local runtime for open-weight language models. It serves a model over HTTP on
this machine at {_OLLAMA_HOST}. The assistant sends one POST to that loopback
address with the system prompt, the retrieved context and the question.

WHY OLLAMA (a local model) INSTEAD OF A CLOUD API.
  - Privacy: the dataset, the solver results and the project documents are
    assembled into the prompt. With a local model none of that leaves the host.
    This is ENFORCED, not merely intended: llm.py refuses any configured host
    that is not a loopback address, so pointing it at a remote box fails loudly.
  - No key and no cost: there is no vendor account, no API key to manage or leak,
    and no per-token billing. The assistant works with no internet connection.
  - Reproducibility: the same model runs on the demo machine every time, with no
    remote model version changing under the project.
  - No vendor dependency: a cloud API would make an offline demo impossible and
    add an external service to something that is meant to be self-contained.
There is therefore no OpenAI, Anthropic or other cloud provider anywhere in the
assistant package - by design, and checked by a test.

WHY llama3.2:3b SPECIFICALLY.
  - 3 billion parameters is small enough to run on an ordinary laptop CPU with no
    GPU, which is what this project must demo on.
  - Its context window is ample for the retrieved context this pipeline sends
    (num_ctx is set to {_NUM_CTX}).
  - In a RAG pipeline the model's job is to read supplied context and write a few
    correct sentences from it - not to recall world facts. A small instruct model
    does that job; its weaker general knowledge is irrelevant here, and arguably
    an advantage, because the answer must come from the context anyway.
  - It is open-weight and free to pull with one command: `ollama pull {_MODEL}`.
The model is a configuration value, not a hard dependency: any Ollama model can
be used by changing ASSISTANT_MODEL.

GENERATION SETTINGS. Temperature is kept very low and the prompt is sent in the
system role, so answers are close to reproducible rather than creative. If Ollama
is not running or the model has not been pulled, the API returns a 503 that names
the exact command to fix it - which is deliberately NOT the same thing as saying
the project data does not cover the question."""),

    # ----------------------------------------------------------------- K ---
    ("grounding-and-sources",
     "How grounding and source attribution work, and what grounded=false means",
     "backend/app/assistant/prompts.py and service.py - grounding and citations",
     """GROUNDING IS A MECHANISM, NOT A PROMISE.
  1. Retrieval runs first. If nothing clears the relevance gate, the model is
     never called at all: the endpoint returns the project's unavailable line
     with grounded=false and reason="no_matching_context". There is no path in
     which an answer is produced with no context behind it.
  2. When chunks are found, they are assembled into a bounded context block.
     Each one arrives labelled with what family it is from and where it came
     from, and the block is fenced with explicit markers. The user message tells
     the model that the text between those markers is DATA, not instructions.
  3. The system prompt forbids inventing facts, forbids calculating any figure
     (every number must appear verbatim in the context), forbids guessing which
     station or line an ambiguous name means, forbids equating route distance
     with energy loss, and forbids claiming quantum advantage.

SOURCES.
The API returns exactly the chunks that went into the context - id, kind, title,
locator and retrieval score - and the panel shows them as chips under the
answer. The kinds are: dataset (a CSV row, a station or the network summary),
doc (project documentation, the tariff reference, this project knowledge), code
(a module, class or function of this repository), and solver (the attached run).
A citation therefore always names something the model could actually read.

WHAT grounded=false MEANS: retrieval found nothing relevant, so the assistant
says so. It does NOT mean the model failed. A model that cannot be reached is a
different outcome entirely - a 503 naming the fix - because "Ollama is not
running here" and "the project data does not cover that" have different
remedies."""),

    # ----------------------------------------------------------------- 4 ---
    ("answering-policy",
     "What the assistant may answer from, and when it must decline",
     "backend/app/assistant/prompts.py - the answering policy",
     """WHAT MAY BE ANSWERED.
An answer is legitimate when it follows from the retrieved GRIDOPT context,
which includes all of:
  1. the project documentation,
  2. the dataset records,
  3. the project's own source code,
  4. the attached optimization run,
  5. the documented behaviour of the algorithms,
  6. a simple, stated logical consequence of any of those.

Explaining what the implementation does IS answering from the project. If the
code in context shows that a window reordering is accepted only when it shortens
the tour, then "why is the hybrid route shorter?" is answerable - by describing
that mechanism - and refusing it would be wrong. "Not written word for word in a
document" is not the same as "unanswerable".

WHAT MUST STILL NOT HAPPEN.
  - No invented results, distances, runtimes, station names, dataset values or
    hardware runs.
  - No figure that is not printed verbatim in the context; no arithmetic.
  - No claim of optimality and no claim of quantum advantage.
  - No intent attributed to the quantum algorithm: describe what the code
    computes and accepts, never what QAOA "understood", "decided" or "proved".
  - No describing a run when none is attached. Run-specific facts - this run's
    origin, distances, improvement, runtime, accepted improvements, energy loss,
    lines used, hourly and annual cost - exist only when the dashboard attached
    the run. Without it, say plainly that no run is attached.

WHEN TO DECLINE.
When the context genuinely does not contain, and does not imply, the answer -
for example a question about a station that is not in this dataset, a quantity
the dataset does not record, or a subject outside the project. Then the
assistant returns its unavailable line rather than filling the gap."""),

    # ----------------------------------------------------------------- L ---
    ("security",
     "Secrets, environment variables and what is demo-grade rather than production-grade",
     "phase2/credentials.py, backend/app/core/config.py, frontend/.env.example",
     """SECRETS AND ENVIRONMENT VARIABLES.
  - A git-ignored .env at the repository root holds the values that must not be
    published: the IBM Quantum token, the Supabase service-role key and similar.
    It is never committed, never printed, never logged and never returned by any
    endpoint. Code reads NAMES from the environment; values stay in the file.
  - The Supabase SERVICE-ROLE key bypasses row-level security. It is a server-
    side secret only: it appears in no browser bundle and in nothing under
    frontend/src.
  - Anything prefixed VITE_ is compiled into the browser bundle and is therefore
    PUBLIC by definition. Only the project URL and the publishable/anon key ever
    belong there - and the frontend refuses to start if a secret key is found in
    a VITE_ variable, because shipping it would hand every visitor a credential.
  - The assistant needs no credential at all: generation is a local model on
    loopback, so there is no key in that path to leak.

WHAT IS PRODUCTION-GRADE HERE.
  - Row-level security on the database tables, with no policy granting the
    anonymous key read access.
  - Secrets kept out of the repository and out of the client bundle.
  - The Supabase JWT verification path in backend/app/core/auth.py: real ES256
    signature verification against the project's published JWKS, with audience,
    issuer and expiry checks.

WHAT IS PRODUCTION-GRADE IN THE SIGN-IN PATH.
  - Sign-in is Supabase Auth. Passwords are handled by Supabase, never stored
    by GRIDOPT and never written to browser storage; the browser holds a
    session, and the access token is verified cryptographically on the API.
  - The username is auth user_metadata - a label - and is never treated as a
    credential.

WHAT IS STILL DEMO-GRADE, STATED PLAINLY.
  - AUTH_MODE=demo, the offline fallback, admits every request without a token.
    It exists so the API runs with no Supabase project reachable; an API served
    in that mode must not be exposed beyond a demo host.
  - CORS is open to the local Vite dev server only.
  - There is no role model: any authenticated user may call every endpoint."""),

    # ----------------------------------------------------------------- M ---
    ("limitations",
     "The project's limitations, stated without hedging",
     "README.md / docs/PHASES.md / phase2/hybrid.py - stated limitations",
     f"""LIMITATIONS OF GRIDOPT, as the project itself records them.

ALGORITHMIC.
  - Nearest Neighbour is a greedy heuristic with no optimality guarantee.
  - The hybrid solver is NOT direct full-network QAOA. It is QAOA applied to
    sliding-window subproblems inside a classical reoptimization loop.
  - A direct position-encoded QAOA over all {_N} stations would need 625 qubits
    and about 29,400 couplings, which is not executable on any simulator or
    device available today.
  - The window decomposition limits the search neighbourhood: only reorderings
    of W consecutive stations, between fixed endpoints, can ever be found. A
    better tour that requires moving a station across the route is outside what
    the method can reach - and that, rather than the quantum optimizer, is the
    binding constraint on this dataset.
  - QAOA is approximate. Neither route is claimed to be optimal.
  - NO QUANTUM ADVANTAGE IS CLAIMED OR DEMONSTRATED.

EXECUTION.
  - Everything reported ran on the local Qiskit Aer SIMULATOR, on a CPU. The
    algorithm is genuine; quantum speed is not being measured.
  - Real hardware is supported but opt-in, and would add device noise and queue
    time.

SCOPE.
  - Energy loss is EVALUATED, not optimized. Neither solver has an energy term in
    its objective.
  - The annualized loss cost is hypothetical: it assumes the modeled loss holds
    for all {HOURS_PER_YEAR} hours of a year, and it is an energy charge only -
    not an electricity bill.

DATA.
  - The dataset is a reduced, static snapshot of a Karnataka transmission
    network, with modeled rather than metered electrical values, no load factor
    and no time series. Results describe this dataset, not the operating grid.

SYSTEM.
  - The sign-in gate is demo-grade (browser-local accounts), not a security
    boundary.
  - The assistant answers only from this project's indexed context; it has no
    outside knowledge and says so when the context does not cover a question."""),
)


#: The questions each entry exists to answer, in the words people ask them.
#:
#: This is not decoration, it is retrieval. BM25 matches literal terms with no
#: stemming, so "Why did you use Ollama?" only finds a chunk that contains the
#: word "use"; an entry that says "Ollama runs locally" everywhere and never
#: "use" loses to a README paragraph that happens to say both. Carrying the
#: question forms in the chunk is the smallest thing that fixes that, and it is
#: honest: these are the questions the entry below actually answers.
#:
#: Every slug in ENTRIES must appear here - `test_assistant_api.py` checks it,
#: so a new entry cannot silently ship without its question forms.
ASKED_AS: dict = {
    "purpose":
        "What is GRIDOPT? What does GRIDOPT stand for? What is the objective of "
        "this project? Why did you use TSP? What problem are you optimizing? "
        "What are you not optimizing?",
    "dataset":
        "What is your dataset? How many stations and transmission lines? What "
        "are the columns? Where did the data come from? What does Capacity_MW "
        "mean? What are the dataset limitations?",
    "graph-model":
        "How did you model the network as a graph? Why did you use Dijkstra? "
        "What are the nodes and edges? Why is the graph sparse? Can one tour leg "
        "use more than one transmission line?",
    "nearest-neighbour":
        "Why did you use Nearest Neighbour? How does the Nearest Neighbour "
        "algorithm work? How is the starting station selected? How is the tour "
        "closed? What are the limitations of NN?",
    "qaoa":
        "What is QAOA? Why did you use QAOA? What is a QUBO? What is the cost "
        "Hamiltonian? What are the QAOA parameters? What is CVaR? What is "
        "COBYLA? How many shots and reps did you use?",
    "625-qubits":
        "Why are 625 qubits required? Why do you need 625 qubits? Why can't you "
        "run 625 qubits directly? Why is full direct QAOA impractical? How many "
        "qubits does a window use?",
    "hybrid-algorithm":
        "What is hybrid QAOA? How does your hybrid algorithm work? How does the "
        "hybrid QAOA reoptimization loop work? What is the window? What are "
        "sweeps? What is splicing? What is the acceptance criterion? How many "
        "subproblems are solved?",
    "why-hybrid-route-differs":
        "Why did QAOA pick this route over NN? Why is the hybrid route shorter "
        "than the NN route? Why did the hybrid QAOA route beat Nearest "
        "Neighbour? How is a candidate ordering accepted?",
    "backends-hardware":
        "What hardware did you use? What is Aer? Is this a real quantum "
        "computer? What happens if IBM hardware is used? Did you achieve "
        "quantum advantage? Is this simulated?",
    "energy-loss":
        "What does Energy_Loss_MW mean? What is the difference between power and "
        "energy? How does a route map to physical lines? Why distinct lines and "
        "not traversals? Why can a shorter route have higher energy loss?",
    "money":
        "How did you calculate the loss cost per hour? Where did Rs 6.60 per kWh "
        "come from? Why is the annualized loss cost in crores? Why is the annual "
        "figure so large? Is the annualized cost actual? What does the tariff "
        "exclude? What is the 8760 hours assumption?",
    "energy-not-optimized":
        "Are you optimizing energy loss? Why not? Does GRIDOPT minimise energy "
        "loss or cost? Would the shorter route save energy? What would an "
        "energy-aware objective need?",
    "backend":
        "Why did you use FastAPI? What are the API endpoints? How does the "
        "backend work? How are errors handled? What does /solve/compare return? "
        "How is the request validated?",
    "frontend":
        "Why did you use React? What happens when the user clicks Run "
        "Optimization? How does the frontend communicate with the backend? What "
        "does the dashboard show? How does route playback work?",
    "database":
        "Why did you use Supabase? What is stored in the database? What is the "
        "expanded view? What is RLS? What authentication do you use? How does "
        "login work?",
    "rag":
        "What is RAG? What does retrieval-augmented generation mean? Why did you "
        "use RAG? How does the assistant work? What is indexed? Why not "
        "fine-tune a model?",
    "bm25":
        "What is BM25? Why did you use BM25 instead of embeddings? Why no vector "
        "database or pgvector? How does retrieval rank chunks? How does an "
        "off-topic question get rejected?",
    "ollama":
        "Why did you use Ollama? Why llama3.2:3b? Why not ChatGPT or the "
        "Anthropic API? Why a local model? Does the assistant need an API key? "
        "What if Ollama is not running?",
    "grounding-and-sources":
        "How do you know the assistant is not hallucinating? What does grounded "
        "false mean? Where do the sources come from? How are answers attributed?",
    "answering-policy":
        "What can the assistant answer? When does it refuse? Can it explain the "
        "code? What if no run is attached?",
    "security":
        "How do you handle secrets? What is in the .env file? What is the "
        "service-role key? Are the frontend environment variables safe? What is "
        "demo-grade rather than production-grade here?",
    "limitations":
        "What are the limitations of this project? What are the weaknesses? Did "
        "you achieve quantum advantage? What would you improve? Is the result "
        "optimal?",
}


#: Caveats that must accompany an entry wherever it is quoted from.
#:
#: A long entry is split into pieces, and retrieval picks whichever piece
#: matches - which may not be the one the caveat was written into. A rupee
#: figure without "energy charge only" and "continuous modeled operation" beside
#: it is the exact misreading this project works hardest to prevent, so the
#: obligation is attached to every piece of the entry rather than to a paragraph
#: of it. Same rule as `context.DATASET_STANDING`, at entry scope.
STANDING: dict = {
    "money":
        "STANDING CAVEAT, true of every rupee figure below: this is an ENERGY "
        "CHARGE ONLY - the value of the lost energy, not an electricity bill - "
        "and any annual figure assumes continuous modeled operation for all "
        f"{HOURS_PER_YEAR} hours of the year. Never present it as an actual "
        "bill or an actual annual loss.",
}


def primer_chunks() -> list:
    """The curated project knowledge, as retrievable chunks.

    Long entries are split with the project's own `chunk_markdown`, for a
    retrieval reason rather than a formatting one. BM25 normalises by document
    length (`retrieval.B`), and this corpus deliberately mixes 400-character CSV
    records with multi-thousand-character explanations. Left whole, the entry
    written to answer "how does the hybrid algorithm work?" scored BELOW an
    incidental four-line settings function, purely on length. Split, each piece
    carries the entry's title, stands on its own, and competes on its terms.
    """
    chunks: list = []
    for slug, title, locator, body in ENTRIES:
        asked = ASKED_AS.get(slug, "")
        standing = STANDING.get(slug, "")
        document = f"# {title}\n\n{body.strip()}\n"
        for position, (_trail, piece) in enumerate(chunk_markdown(document)):
            chunks.append(Chunk(
                id=f"primer:{slug}:{position}",
                kind="doc",
                title=title,
                locator=locator,
                # The question forms go on every piece, not only the first: a
                # question retrieves whichever piece answers it, and a piece
                # that cannot be found is not knowledge.
                text=(f"GRIDOPT PROJECT KNOWLEDGE - {title}.\n"
                      f"This answers questions such as: {asked}\n"
                      + (f"{standing}\n" if standing else "")
                      + f"\n{piece}"),
                metadata={"topic": slug, "part": position},
            ))
    return chunks
