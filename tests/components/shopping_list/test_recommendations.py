"""Tests for shopping list smart recommendations."""

import pytest
from homeassistant.components.shopping_list.recommendations import ShoppingRecommender


@pytest.fixture
def recommender():
    return ShoppingRecommender()


def test_observe_and_suggest(tmp_path, recommender):
    # simulate user adding milk + bread + egg together
    recommender.observe_list(["milk", "bread", "egg"])

    # assert co-occurrence relationships are tracked
    suggestions = recommender.suggest("milk")
    assert "bread" in suggestions
    assert "egg" in suggestions

def test_empty_recommendations(recommender):
    assert recommender.suggest("unknown_item") == []
