"""Simple local recommendations for the shopping list."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import tempfile

if os.access("/config", os.W_OK):
    STORAGE_DIR = Path("/config/.storage")
else:
    STORAGE_DIR = Path(tempfile.gettempdir()) / ".storage"

STORAGE_PATH = STORAGE_DIR / "shopping_recommendations.json"


class ShoppingRecommender:
    """Naive co-occurrence based recommender."""

    def __init__(self) -> None:
        """Initialize the recommender."""
        self.cooccur: dict[str, Counter] = defaultdict(Counter)
        self._load()

    def _load(self) -> None:
        """Load stored co-occurrence data."""
        if STORAGE_PATH.exists():
            try:
                self.cooccur = defaultdict(
                    Counter,
                    {
                        k: Counter(v)
                        for k, v in json.loads(
                            STORAGE_PATH.read_text(encoding="utf-8")
                        ).items()
                    },
                )
            except Exception:  # noqa: BLE001
                self.cooccur = defaultdict(Counter)

    def _save(self) -> None:
        """Save co-occurrence data to storage."""
        STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)  # check if exists
        STORAGE_PATH.write_text(
            json.dumps({k: dict(v) for k, v in self.cooccur.items()}, indent=2),
            encoding="utf-8",
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
