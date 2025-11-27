from pathlib import Path
import networkx as nx


def export_graphml(G: nx.Graph, path: str = "output/graph.graphml") -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, path)
    return path


def export_gexf(G: nx.Graph, path: str = "output/graph.gexf") -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(G, path)
    return path
