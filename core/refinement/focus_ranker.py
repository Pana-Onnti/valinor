"""
FocusRanker — re-ranks entity/table priorities based on historical finding density.
Modifies the entity_map's internal ordering so Query Builder focuses on high-signal tables first.
"""
from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile


class FocusRanker:

    def rerank_entity_map(self, entity_map: Dict[str, Any], profile: "ClientProfile") -> Dict[str, Any]:
        """
        Returns a copy of entity_map with entities sorted by historical signal weight.
        High-weight tables → Query Builder generates more queries for them.
        """
        if not profile.table_weights or not entity_map.get("entities"):
            return entity_map

        entities = entity_map.get("entities", {})
        weights = profile.table_weights

        # Sort entities by weight (desc), unknown tables get weight 0.5
        sorted_entities = dict(
            sorted(
                entities.items(),
                key=lambda kv: weights.get(kv[1].get("table", kv[0]), 0.5),
                reverse=True,
            )
        )

        return {**entity_map, "entities": sorted_entities, "_focus_ranked": True}
