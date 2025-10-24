"""Tests for Shopping List smart recommendations."""

from homeassistant.components.shopping_list.recommendations import ShoppingRecommender
from homeassistant.core import HomeAssistant


async def test_observe_and_suggest_basic(hass: HomeAssistant) -> None:
    """Test that observing items creates expected suggestions."""
    rec = ShoppingRecommender()
    rec.observe_list(["milk", "bread", "eggs"])

    suggestions = rec.suggest("milk")
    assert "bread" in suggestions
    assert "eggs" in suggestions
    assert len(suggestions) <= 3


async def test_suggest_returns_empty_for_unknown_item(hass: HomeAssistant) -> None:
    """Test that unknown items return an empty list."""
    rec = ShoppingRecommender()
    result = rec.suggest("nonexistent")
    assert result == []


async def test_cooccurrence_counts_increase(hass: HomeAssistant) -> None:
    """Test that repeated co-occurrences increase the stored counts."""
    rec = ShoppingRecommender()
    rec.observe_list(["milk", "bread"])
    rec.observe_list(["milk", "bread"])

    assert rec.cooccur["milk"]["bread"] >= 2
