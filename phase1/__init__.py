"""Phase 1 - dataset loading, network graph, classical Nearest Neighbour TSP.

Written from scratch for the "Hybrid Quantum-Classical Optimization for Energy
Distribution (TSP)" project. Nothing here fabricates network data: every station,
connection and cost comes from the CSV in `data/`.
"""

__all__ = ["data_loader", "network", "nn_tsp", "visualize"]
