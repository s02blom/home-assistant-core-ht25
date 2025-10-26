"""Test shopping list component."""

import base64
import csv
from http import HTTPStatus

import pytest

from homeassistant.components.shopping_list import NoMatchingShoppingListItem
from homeassistant.components.shopping_list.const import (
    ATTR_REVERSE,
    DOMAIN,
    EVENT_SHOPPING_LIST_UPDATED,
    SERVICE_ADD_ITEM,
    SERVICE_CLEAR_COMPLETED_ITEMS,
    SERVICE_COMPLETE_ITEM,
    SERVICE_EXPORT,
    SERVICE_REMOVE_ITEM,
    SERVICE_SORT,
)
from homeassistant.components.websocket_api import (
    ERR_INVALID_FORMAT,
    ERR_NOT_FOUND,
    TYPE_RESULT,
)
from homeassistant.const import ATTR_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from tests.common import async_capture_events
from tests.typing import ClientSessionGenerator, WebSocketGenerator


async def test_add_item(hass: HomeAssistant, sl_setup) -> None:
    """Test adding an item intent."""

    response = await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": " beer "}}
    )
    assert len(hass.data[DOMAIN].items) == 1
    assert hass.data[DOMAIN].items[0]["name"] == "beer"  # name was trimmed

    # Response text is now handled by default conversation agent
    assert response.response_type == intent.IntentResponseType.ACTION_DONE


async def test_remove_item(hass: HomeAssistant, sl_setup) -> None:
    """Test removiung list items."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "cheese"}}
    )

    assert len(hass.data[DOMAIN].items) == 2

    # Remove a single item
    item_id = hass.data[DOMAIN].items[0]["id"]
    await hass.data[DOMAIN].async_remove(item_id)

    assert len(hass.data[DOMAIN].items) == 1

    item = hass.data[DOMAIN].items[0]
    assert item["name"] == "cheese"

    # Trying to remove the same item twice should fail
    with pytest.raises(NoMatchingShoppingListItem):
        await hass.data[DOMAIN].async_remove(item_id)


async def test_update_list(hass: HomeAssistant, sl_setup) -> None:
    """Test updating all list items."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "cheese"}}
    )

    # Update a single attribute, other attributes shouldn't change
    await hass.data[DOMAIN].async_update_list({"complete": True})

    beer = hass.data[DOMAIN].items[0]
    assert beer["name"] == "beer"
    assert beer["complete"] is True

    cheese = hass.data[DOMAIN].items[1]
    assert cheese["name"] == "cheese"
    assert cheese["complete"] is True

    # Update multiple attributes
    await hass.data[DOMAIN].async_update_list({"name": "dupe", "complete": False})

    beer = hass.data[DOMAIN].items[0]
    assert beer["name"] == "dupe"
    assert beer["complete"] is False

    cheese = hass.data[DOMAIN].items[1]
    assert cheese["name"] == "dupe"
    assert cheese["complete"] is False


async def test_clear_completed_items(hass: HomeAssistant, sl_setup) -> None:
    """Test clear completed list items."""
    await intent.async_handle(
        hass,
        "test",
        "HassShoppingListAddItem",
        {"item": {"value": "beer"}},
    )

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "cheese"}}
    )

    assert len(hass.data[DOMAIN].items) == 2

    # Update a single attribute, other attributes shouldn't change
    await hass.data[DOMAIN].async_update_list({"complete": True})

    await hass.data[DOMAIN].async_clear_completed()

    assert len(hass.data[DOMAIN].items) == 0


async def test_recent_items_intent(hass: HomeAssistant, sl_setup) -> None:
    """Test recent items."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "soda"}}
    )

    response = await intent.async_handle(hass, "test", "HassShoppingListLastItems")

    assert (
        response.speech["plain"]["speech"]
        == "These are the top 3 items on your shopping list: soda, wine, beer"
    )


async def test_deprecated_api_get_all(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )

    client = await hass_client()
    resp = await client.get("/api/shopping_list")

    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "beer"
    assert not data[0]["complete"]
    assert data[1]["name"] == "wine"
    assert not data[1]["complete"]


async def test_ws_get_items(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test get shopping_list items websocket command."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )

    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)

    await client.send_json({"id": 5, "type": "shopping_list/items"})
    msg = await client.receive_json()
    assert msg["success"] is True
    assert len(events) == 0

    assert msg["id"] == 5
    assert msg["type"] == TYPE_RESULT
    assert msg["success"]
    data = msg["result"]
    assert len(data) == 2
    assert data[0]["name"] == "beer"
    assert not data[0]["complete"]
    assert data[1]["name"] == "wine"
    assert not data[1]["complete"]


async def test_deprecated_api_update(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )

    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]

    client = await hass_client()
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    resp = await client.post(
        f"/api/shopping_list/item/{beer_id}", json={"name": "soda"}
    )

    assert resp.status == HTTPStatus.OK
    assert len(events) == 1
    data = await resp.json()
    assert data == {"id": beer_id, "name": "soda", "complete": False, "description": ""}

    resp = await client.post(
        f"/api/shopping_list/item/{wine_id}", json={"complete": True}
    )

    assert resp.status == HTTPStatus.OK
    assert len(events) == 2
    data = await resp.json()
    assert data == {"id": wine_id, "name": "wine", "complete": True, "description": ""}

    beer, wine = hass.data["shopping_list"].items
    assert beer == {"id": beer_id, "name": "soda", "complete": False, "description": ""}
    assert wine == {"id": wine_id, "name": "wine", "complete": True, "description": ""}


async def test_ws_update_item(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test update shopping_list item websocket command."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )

    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json(
        {
            "id": 5,
            "type": "shopping_list/items/update",
            "item_id": beer_id,
            "name": "soda",
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    data = msg["result"]
    assert data == {"id": beer_id, "name": "soda", "complete": False, "description": ""}
    assert len(events) == 1

    await client.send_json(
        {
            "id": 6,
            "type": "shopping_list/items/update",
            "item_id": wine_id,
            "complete": True,
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    data = msg["result"]
    assert data == {"id": wine_id, "name": "wine", "complete": True, "description": ""}
    assert len(events) == 2

    beer, wine = hass.data["shopping_list"].items
    assert beer == {"id": beer_id, "name": "soda", "complete": False, "description": ""}
    assert wine == {"id": wine_id, "name": "wine", "complete": True, "description": ""}


async def test_api_update_fails(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )

    client = await hass_client()
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    resp = await client.post("/api/shopping_list/non_existing", json={"name": "soda"})

    assert resp.status == HTTPStatus.NOT_FOUND
    assert len(events) == 0

    beer_id = hass.data["shopping_list"].items[0]["id"]
    resp = await client.post(f"/api/shopping_list/item/{beer_id}", json={"name": 123})

    assert resp.status == HTTPStatus.BAD_REQUEST


async def test_ws_update_item_fail(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test failure of update shopping_list item websocket command."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json(
        {
            "id": 5,
            "type": "shopping_list/items/update",
            "item_id": "non_existing",
            "name": "soda",
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    data = msg["error"]
    assert data == {"code": "item_not_found", "message": "Item not found"}
    assert len(events) == 0

    await client.send_json({"id": 6, "type": "shopping_list/items/update", "name": 123})
    msg = await client.receive_json()
    assert msg["success"] is False
    assert len(events) == 0


async def test_deprecated_api_clear_completed(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )

    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]

    client = await hass_client()
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)

    # Mark beer as completed
    resp = await client.post(
        f"/api/shopping_list/item/{beer_id}", json={"complete": True}
    )
    assert resp.status == HTTPStatus.OK
    assert len(events) == 1

    resp = await client.post("/api/shopping_list/clear_completed")
    assert resp.status == HTTPStatus.OK
    assert len(events) == 2

    items = hass.data["shopping_list"].items
    assert len(items) == 1

    assert items[0] == {
        "id": wine_id,
        "name": "wine",
        "complete": False,
        "description": "",
    }


async def test_ws_clear_items(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test clearing shopping_list items websocket command."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )
    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json(
        {
            "id": 5,
            "type": "shopping_list/items/update",
            "item_id": beer_id,
            "complete": True,
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    assert len(events) == 1

    await client.send_json({"id": 6, "type": "shopping_list/items/clear"})
    msg = await client.receive_json()
    assert msg["success"] is True
    items = hass.data["shopping_list"].items
    assert len(items) == 1
    assert items[0] == {
        "id": wine_id,
        "name": "wine",
        "complete": False,
        "description": "",
    }
    assert len(events) == 2


async def test_deprecated_api_create(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    client = await hass_client()
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    resp = await client.post("/api/shopping_list/item", json={"name": "soda"})

    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    assert data["name"] == "soda"
    assert data["complete"] is False
    assert len(events) == 1

    items = hass.data["shopping_list"].items
    assert len(items) == 1
    assert items[0]["name"] == "soda"
    assert items[0]["complete"] is False


async def test_deprecated_api_create_fail(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the API."""

    client = await hass_client()
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    resp = await client.post("/api/shopping_list/item", json={"name": 1234})

    assert resp.status == HTTPStatus.BAD_REQUEST
    assert len(hass.data["shopping_list"].items) == 0
    assert len(events) == 0


async def test_ws_add_item(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test adding shopping_list item websocket command."""
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json({"id": 5, "type": "shopping_list/items/add", "name": "soda"})
    msg = await client.receive_json()
    assert msg["success"] is True
    data = msg["result"]
    assert data["name"] == "soda"
    assert data["complete"] is False
    assert len(events) == 1

    items = hass.data["shopping_list"].items
    assert len(items) == 1
    assert items[0]["name"] == "soda"
    assert items[0]["complete"] is False


async def test_ws_add_item_fail(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test adding shopping_list item failure websocket command."""
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json({"id": 5, "type": "shopping_list/items/add", "name": 123})
    msg = await client.receive_json()
    assert msg["success"] is False
    assert len(events) == 0
    assert len(hass.data["shopping_list"].items) == 0


async def test_ws_remove_item(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test removing shopping_list item websocket command."""
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json({"id": 5, "type": "shopping_list/items/add", "name": "soda"})
    msg = await client.receive_json()
    first_item_id = msg["result"]["id"]
    await client.send_json(
        {"id": 6, "type": "shopping_list/items/add", "name": "cheese"}
    )
    msg = await client.receive_json()
    assert len(events) == 2

    items = hass.data["shopping_list"].items
    assert len(items) == 2

    await client.send_json(
        {"id": 7, "type": "shopping_list/items/remove", "item_id": first_item_id}
    )
    msg = await client.receive_json()
    assert len(events) == 3
    assert msg["success"] is True

    items = hass.data["shopping_list"].items
    assert len(items) == 1
    assert items[0]["name"] == "cheese"


async def test_ws_remove_item_fail(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test removing shopping_list item failure websocket command."""
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json({"id": 5, "type": "shopping_list/items/add", "name": "soda"})
    msg = await client.receive_json()
    await client.send_json({"id": 6, "type": "shopping_list/items/remove"})
    msg = await client.receive_json()
    assert msg["success"] is False
    assert len(events) == 1
    assert len(hass.data["shopping_list"].items) == 1


async def test_ws_reorder_items(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test reordering shopping_list items websocket command."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "apple"}}
    )

    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]
    apple_id = hass.data["shopping_list"].items[2]["id"]

    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await client.send_json(
        {
            "id": 6,
            "type": "shopping_list/items/reorder",
            "item_ids": [wine_id, apple_id, beer_id],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    assert len(events) == 1
    assert hass.data["shopping_list"].items[0] == {
        "id": wine_id,
        "name": "wine",
        "complete": False,
        "description": "",
    }
    assert hass.data["shopping_list"].items[1] == {
        "id": apple_id,
        "name": "apple",
        "complete": False,
        "description": "",
    }
    assert hass.data["shopping_list"].items[2] == {
        "id": beer_id,
        "name": "beer",
        "complete": False,
        "description": "",
    }

    # Mark wine as completed.
    await client.send_json(
        {
            "id": 7,
            "type": "shopping_list/items/update",
            "item_id": wine_id,
            "complete": True,
        }
    )
    _ = await client.receive_json()
    assert len(events) == 2

    await client.send_json(
        {
            "id": 8,
            "type": "shopping_list/items/reorder",
            "item_ids": [apple_id, beer_id],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is True
    assert len(events) == 3
    assert hass.data["shopping_list"].items[0] == {
        "id": apple_id,
        "name": "apple",
        "complete": False,
        "description": "",
    }
    assert hass.data["shopping_list"].items[1] == {
        "id": beer_id,
        "name": "beer",
        "complete": False,
        "description": "",
    }
    assert hass.data["shopping_list"].items[2] == {
        "id": wine_id,
        "name": "wine",
        "complete": True,
        "description": "",
    }


async def test_ws_reorder_items_failure(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test reordering shopping_list items websocket command."""
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "beer"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "wine"}}
    )
    await intent.async_handle(
        hass, "test", "HassShoppingListAddItem", {"item": {"value": "apple"}}
    )

    beer_id = hass.data["shopping_list"].items[0]["id"]
    wine_id = hass.data["shopping_list"].items[1]["id"]
    apple_id = hass.data["shopping_list"].items[2]["id"]

    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)

    # Testing sending bad item id.
    await client.send_json(
        {
            "id": 8,
            "type": "shopping_list/items/reorder",
            "item_ids": [wine_id, apple_id, beer_id, "BAD_ID"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == ERR_NOT_FOUND
    assert len(events) == 0

    # Testing not sending all unchecked item ids.
    await client.send_json(
        {
            "id": 9,
            "type": "shopping_list/items/reorder",
            "item_ids": [wine_id, apple_id],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] is False
    assert msg["error"]["code"] == ERR_INVALID_FORMAT
    assert len(events) == 0


async def test_add_item_service(hass: HomeAssistant, sl_setup) -> None:
    """Test adding shopping_list item service."""
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 1
    assert len(events) == 1


async def test_remove_item_service(hass: HomeAssistant, sl_setup) -> None:
    """Test removing shopping_list item service."""
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "cheese"},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 2
    assert len(events) == 2

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 1
    assert hass.data[DOMAIN].items[0]["name"] == "cheese"
    assert len(events) == 3


async def test_clear_completed_items_service(hass: HomeAssistant, sl_setup) -> None:
    """Test clearing completed shopping_list items service."""
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 1
    assert len(events) == 1

    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 1
    assert len(events) == 1

    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEAR_COMPLETED_ITEMS,
        {},
        blocking=True,
    )
    assert len(hass.data[DOMAIN].items) == 0
    assert len(events) == 1


async def test_sort_list_service(hass: HomeAssistant, sl_setup) -> None:
    """Test sort_all service."""

    for name in ("zzz", "ddd", "aaa"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_ITEM,
            {ATTR_NAME: name},
            blocking=True,
        )

    # sort ascending
    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SORT,
        {ATTR_REVERSE: False},
        blocking=True,
    )

    assert hass.data[DOMAIN].items[0][ATTR_NAME] == "aaa"
    assert hass.data[DOMAIN].items[1][ATTR_NAME] == "ddd"
    assert hass.data[DOMAIN].items[2][ATTR_NAME] == "zzz"
    assert len(events) == 1

    # sort descending
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SORT,
        {ATTR_REVERSE: True},
        blocking=True,
    )

    assert hass.data[DOMAIN].items[0][ATTR_NAME] == "zzz"
    assert hass.data[DOMAIN].items[1][ATTR_NAME] == "ddd"
    assert hass.data[DOMAIN].items[2][ATTR_NAME] == "aaa"
    assert len(events) == 2


async def test_export_list_service_json(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting shopping list to json format via service."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "cheese"},
        blocking=True,
    )

    # Mark one item as complete
    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_ITEM,
        {ATTR_NAME: "beer"},
        blocking=True,
    )

    # Test export with json format (default)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "json"},
        blocking=True,
        return_response=True,
    )

    # Verify the response structure
    assert "content" in response
    assert "filename" in response
    assert "mime_type" in response
    assert response["filename"] == "shopping_list.json"
    assert response["mime_type"] == "application/json"

    # Verify the exported data (content is the actual list, not a JSON string)
    exported_data = response["content"]
    assert isinstance(exported_data, list)

    assert len(exported_data) == 2
    assert any(
        item["name"] == "beer" and item["complete"] is True for item in exported_data
    )
    assert any(
        item["name"] == "cheese" and item["complete"] is False for item in exported_data
    )


async def test_export_list_service_csv(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting shopping list to csv format via service."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "milk"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "eggs"},
        blocking=True,
    )

    # Test export with csv format
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "csv"},
        blocking=True,
        return_response=True,
    )

    # Verify the response structure
    assert "content" in response
    assert "filename" in response
    assert "mime_type" in response
    assert response["filename"] == "shopping_list.csv"
    assert response["mime_type"] == "text/csv"

    # Parse and verify the CSV content
    csv_content = response["content"]
    reader = csv.DictReader(csv_content.splitlines())
    rows = list(reader)

    assert len(rows) == 2
    assert any(row["name"] == "milk" and row["complete"] == "False" for row in rows)
    assert any(row["name"] == "eggs" and row["complete"] == "False" for row in rows)


async def test_ws_export_list(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test exporting shopping list via websocket command."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "bread"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "butter"},
        blocking=True,
    )

    client = await hass_ws_client(hass)

    # Test websocket export (defaults to json)
    await client.send_json({"id": 10, "type": "shopping_list/export"})
    msg = await client.receive_json()

    assert msg["success"] is True
    assert msg["id"] == 10
    assert msg["type"] == TYPE_RESULT

    # Verify the response contains the export data
    result = msg["result"]
    assert "content" in result
    assert "filename" in result
    assert "mime_type" in result
    assert result["filename"] == "shopping_list.json"
    assert result["mime_type"] == "application/json"

    # Verify the exported data (content is the actual list, not a JSON string)
    exported_data = result["content"]
    assert isinstance(exported_data, list)

    assert len(exported_data) == 2
    assert any(item["name"] == "bread" for item in exported_data)
    assert any(item["name"] == "butter" for item in exported_data)


async def test_export_list_service_pdf(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting shopping list to pdf format via service."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "apples"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "oranges"},
        blocking=True,
    )

    # Mark one item as complete
    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_ITEM,
        {ATTR_NAME: "apples"},
        blocking=True,
    )

    # Test export with pdf format
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "pdf"},
        blocking=True,
        return_response=True,
    )

    # Verify the response structure
    assert "content" in response
    assert "filename" in response
    assert "mime_type" in response
    assert "encoding" in response
    assert response["filename"] == "shopping_list.pdf"
    assert response["mime_type"] == "application/pdf"
    assert response["encoding"] == "base64"

    # Decode base64 and verify it's a valid PDF file (starts with PDF magic bytes)
    pdf_content = base64.b64decode(response["content"])
    assert pdf_content[:4] == b"%PDF"


async def test_export_empty_list_json(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting empty shopping list to json format."""
    # Don't add any items - test with empty list
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "json"},
        blocking=True,
        return_response=True,
    )

    # Verify the response structure
    assert "content" in response
    assert "filename" in response
    assert "mime_type" in response
    assert response["filename"] == "shopping_list.json"
    assert response["mime_type"] == "application/json"

    # Verify the exported data is an empty array (content is the actual list)
    exported_data = response["content"]
    assert isinstance(exported_data, list)
    assert len(exported_data) == 0


async def test_export_empty_list_csv(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting empty shopping list to csv format."""
    # Don't add any items - test with empty list
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "csv"},
        blocking=True,
        return_response=True,
    )

    # Verify the response structure
    assert "content" in response
    assert "filename" in response
    assert "mime_type" in response
    assert response["filename"] == "shopping_list.csv"
    assert response["mime_type"] == "text/csv"

    # Parse and verify the CSV has headers but no data rows
    csv_content = response["content"]
    # One header line, no data rows
    lines = csv_content.strip().split("\n")
    assert len(lines) == 1

    # Check header columns (order-insensitive and future-proof)
    reader = csv.DictReader(lines)
    assert reader.fieldnames is not None
    assert set(reader.fieldnames) == {"id", "name", "description", "complete"}

    # Ensure there are no data rows
    assert sum(1 for _ in reader) == 0


async def test_ws_export_list_csv(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test exporting shopping list as CSV via websocket command."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "pasta"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "sauce"},
        blocking=True,
    )

    client = await hass_ws_client(hass)

    # Test websocket export with CSV format
    await client.send_json(
        {"id": 11, "type": "shopping_list/export", "filetype": "csv"}
    )
    msg = await client.receive_json()

    assert msg["success"] is True
    assert msg["id"] == 11
    assert msg["type"] == TYPE_RESULT

    # Verify the response contains the export data
    result = msg["result"]
    assert "content" in result
    assert "filename" in result
    assert "mime_type" in result
    assert result["filename"] == "shopping_list.csv"
    assert result["mime_type"] == "text/csv"

    # Parse and verify the CSV data
    csv_content = result["content"]
    reader = csv.DictReader(csv_content.splitlines())
    rows = list(reader)

    assert len(rows) == 2
    assert any(row["name"] == "pasta" for row in rows)
    assert any(row["name"] == "sauce" for row in rows)


async def test_ws_export_list_pdf(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, sl_setup
) -> None:
    """Test exporting shopping list as PDF via websocket command."""
    # Add items to the shopping list
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "carrots"},
        blocking=True,
    )

    client = await hass_ws_client(hass)

    # Test websocket export with PDF format
    await client.send_json(
        {"id": 12, "type": "shopping_list/export", "filetype": "pdf"}
    )
    msg = await client.receive_json()

    assert msg["success"] is True
    assert msg["id"] == 12
    assert msg["type"] == TYPE_RESULT

    # Verify the response contains the export data
    result = msg["result"]
    assert "content" in result
    assert "filename" in result
    assert "mime_type" in result
    assert "encoding" in result
    assert result["filename"] == "shopping_list.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["encoding"] == "base64"

    # Decode and verify it's a valid PDF
    pdf_content = base64.b64decode(result["content"])
    assert pdf_content[:4] == b"%PDF"


async def test_export_list_default_format(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting shopping list with default format (should be json)."""
    # Add an item
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "test_item"},
        blocking=True,
    )

    # Call export without specifying filetype (should default to json)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {},
        blocking=True,
        return_response=True,
    )

    # Verify it defaults to JSON format
    assert response["filename"] == "shopping_list.json"
    assert response["mime_type"] == "application/json"

    # Verify content is the actual list
    exported_data = response["content"]
    assert isinstance(exported_data, list)
    assert len(exported_data) == 1
    assert exported_data[0]["name"] == "test_item"


async def test_export_list_special_characters(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting shopping list with special characters in item names."""
    # Add items with special characters
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "Café au lait"},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: 'Items with "quotes" & ampersands'},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ITEM,
        {ATTR_NAME: "Unicode: 你好 🛒"},
        blocking=True,
    )

    # Test JSON export
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "json"},
        blocking=True,
        return_response=True,
    )

    exported_data = response["content"]
    assert isinstance(exported_data, list)
    assert len(exported_data) == 3
    names = [item["name"] for item in exported_data]
    assert "Café au lait" in names
    assert 'Items with "quotes" & ampersands' in names
    assert "Unicode: 你好 🛒" in names

    # Test CSV export
    csv_response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "csv"},
        blocking=True,
        return_response=True,
    )

    csv_content = csv_response["content"]
    reader = csv.DictReader(csv_content.splitlines())
    rows = list(reader)
    csv_names = [row["name"] for row in rows]
    assert "Café au lait" in csv_names
    assert 'Items with "quotes" & ampersands' in csv_names
    assert "Unicode: 你好 🛒" in csv_names


async def test_export_list_large_list(hass: HomeAssistant, sl_setup) -> None:
    """Test exporting a large shopping list."""
    # Add 100 items
    for i in range(100):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_ITEM,
            {ATTR_NAME: f"item_{i}"},
            blocking=True,
        )

    # Export as JSON
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "json"},
        blocking=True,
        return_response=True,
    )

    exported_data = response["content"]
    assert isinstance(exported_data, list)
    assert len(exported_data) == 100

    # Verify all items are present
    names = {item["name"] for item in exported_data}
    for i in range(100):
        assert f"item_{i}" in names


async def test_export_list_mixed_completion_status(
    hass: HomeAssistant, sl_setup
) -> None:
    """Test exporting shopping list with mixed completion statuses."""
    # Add and complete some items
    items = ["item1", "item2", "item3", "item4", "item5"]
    completed = ["item1", "item3", "item5"]

    for item_name in items:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_ITEM,
            {ATTR_NAME: item_name},
            blocking=True,
        )

    for item_name in completed:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_COMPLETE_ITEM,
            {ATTR_NAME: item_name},
            blocking=True,
        )

    # Export as JSON
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT,
        {"filetype": "json"},
        blocking=True,
        return_response=True,
    )

    exported_data = response["content"]
    assert isinstance(exported_data, list)
    assert len(exported_data) == 5

    # Verify completion status
    for item in exported_data:
        if item["name"] in completed:
            assert item["complete"] is True
        else:
            assert item["complete"] is False


async def test_service_sort_by_name_and_description(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, sl_setup
) -> None:
    """Test the shopping_list.sort service sorts correctly by name and description."""
    client = await hass_client()

    # Add items with both names and descriptions
    await client.post(
        "/api/shopping_list/item", json={"name": "banana", "description": "yellow"}
    )
    await client.post(
        "/api/shopping_list/item", json={"name": "apple", "description": "green"}
    )
    await client.post(
        "/api/shopping_list/item", json={"name": "carrot", "description": "orange"}
    )

    events = async_capture_events(hass, EVENT_SHOPPING_LIST_UPDATED)

    # Sort by name (alphabetical)
    await hass.services.async_call(DOMAIN, "sort", {"by": "name"}, blocking=True)
    assert len(events) >= 1
    assert events[-1].data["action"] == "sorted_by_name"

    items = hass.data[DOMAIN].items
    names = [item["name"] for item in items]
    assert names == ["apple", "banana", "carrot"]

    # Sort by name in reverse
    await hass.services.async_call(
        DOMAIN, "sort", {"by": "name", "reverse": True}, blocking=True
    )
    assert events[-1].data["action"] == "sorted_by_name"
    items = hass.data[DOMAIN].items
    names = [item["name"] for item in items]
    assert names == ["carrot", "banana", "apple"]

    # Sort by description
    await hass.services.async_call(DOMAIN, "sort", {"by": "description"}, blocking=True)
    assert events[-1].data["action"] == "sorted_by_description"
    items = hass.data[DOMAIN].items
    descriptions = [item["description"] for item in items]
    assert descriptions == ["green", "orange", "yellow"]

    # Sort by description in reverse
    await hass.services.async_call(
        DOMAIN, "sort", {"by": "description", "reverse": True}, blocking=True
    )
    assert events[-1].data["action"] == "sorted_by_description"
    items = hass.data[DOMAIN].items
    descriptions = [item["description"] for item in items]
    assert descriptions == ["yellow", "orange", "green"]
