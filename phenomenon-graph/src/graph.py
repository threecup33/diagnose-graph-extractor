from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from .schema import CausalEdge, PhenomenonGraph, PhenomenonNode


class MergedGraph:
    """Incrementally merges multiple PhenomenonGraph instances into one graph.

    Node deduplication is based on exact label match (case-sensitive).
    Edge deduplication is based on (from_id, to_id, relation); weights accumulate.
    """

    def __init__(self) -> None:
        # label -> PhenomenonNode (canonical)
        self._nodes: Dict[str, PhenomenonNode] = {}
        # (from_id, to_id, relation) -> CausalEdge
        self._edges: Dict[Tuple[str, str, str], CausalEdge] = {}
        # label -> canonical id
        self._label_to_id: Dict[str, str] = {}

    def add_graph(self, graph: PhenomenonGraph) -> None:
        # Map old node ids to canonical ids in this merged graph
        id_map: Dict[str, str] = {}

        for node in graph.nodes:
            if node.label in self._label_to_id:
                # Node already exists; map incoming id to existing canonical id
                canonical_id = self._label_to_id[node.label]
                id_map[node.id] = canonical_id
                # If newly verified, update the stored node
                if node.verified and not self._nodes[canonical_id].verified:
                    self._nodes[canonical_id] = self._nodes[canonical_id].model_copy(
                        update={"verified": True}
                    )
            else:
                # New node: use the incoming id as canonical (ensure uniqueness)
                canonical_id = self._make_unique_id(node.id)
                new_node = node.model_copy(update={"id": canonical_id})
                self._nodes[canonical_id] = new_node
                self._label_to_id[node.label] = canonical_id
                id_map[node.id] = canonical_id

        for edge in graph.edges:
            from_id = id_map.get(edge.from_id, edge.from_id)
            to_id = id_map.get(edge.to_id, edge.to_id)
            key = (from_id, to_id, edge.relation)
            if key in self._edges:
                existing = self._edges[key]
                self._edges[key] = existing.model_copy(
                    update={"weight": existing.weight + edge.weight}
                )
            else:
                self._edges[key] = edge.model_copy(
                    update={"from_id": from_id, "to_id": to_id}
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.model_dump() for n in self._nodes.values()],
            "edges": [e.model_dump() for e in self._edges.values()],
        }

    def summary(self) -> str:
        node_count = len(self._nodes)
        edge_count = len(self._edges)

        sorted_edges = sorted(
            self._edges.values(), key=lambda e: e.weight, reverse=True
        )
        top_n = min(5, len(sorted_edges))
        top_lines: List[str] = []
        for e in sorted_edges[:top_n]:
            from_label = self._nodes.get(e.from_id, PhenomenonNode(
                id=e.from_id, label=e.from_id, type="intermediate"
            )).label
            to_label = self._nodes.get(e.to_id, PhenomenonNode(
                id=e.to_id, label=e.to_id, type="intermediate"
            )).label
            top_lines.append(
                f"  [{e.weight:>3}] {from_label!r} --{e.relation}--> {to_label!r}"
            )

        lines = [
            "=== Merged Graph Summary ===",
            f"Nodes : {node_count}",
            f"Edges : {edge_count}",
            f"Top {top_n} edges by weight:",
        ] + top_lines

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_unique_id(self, preferred: str) -> str:
        if preferred not in self._nodes:
            return preferred
        counter = 2
        while f"{preferred}_{counter}" in self._nodes:
            counter += 1
        return f"{preferred}_{counter}"
