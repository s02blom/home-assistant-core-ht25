"""Simple local recommendations for the shopping list."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

STORAGE_PATH = Path(".storage/shopping_recommendations.json")


class ShoppingRecommender:
    """Naive co-occurrence based recommender."""

    def __init__(self) -> None:
        """Initialize the recommender."""
        self.cooccur: dict[str, Counter] = defaultdict(Counter)
        self._load()

    def _load(self) -> None:
        if STORAGE_PATH.exists():
            try:
                self.cooccur = defaultdict(
                    Counter,
                    {
                        k: Counter(v)
                        for k, v in json.loads(STORAGE_PATH.read_text()).items()
                    },
                )
            except Exception:  # noqa: BLE001
                self.cooccur = defaultdict(Counter)

    def _save(self) -> None:
        STORAGE_PATH.write_text(
            json.dumps({k: dict(v) for k, v in self.cooccur.items()}, indent=2)
        )

    def observe_list(self, items: list[str]) -> None:
        """Update co-occurrence stats from a list of items."""
        norm = [i.lower() for i in items if i.strip()]
        for a in norm:
            for b in norm:
                if a != b:
                    self.cooccur[a][b] += 1
        self._save()

    def suggest(self, item: str, limit: int = 3) -> list[str]:
        """Return top-N suggestions for an item."""
        item = item.lower()
        if item not in self.cooccur:
            return []
        return [name for name, _ in self.cooccur[item].most_common(limit)]


recommender = ShoppingRecommender()
