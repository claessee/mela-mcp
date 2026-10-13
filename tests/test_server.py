import asyncio
import json

import pytest
from mcp_types import CallToolResult

from mela_mcp import server

TOOLS = {"search_recipes", "get_recipe", "list_tags", "list_recipes",
         "list_favorites", "list_want_to_cook", "diagnose_library"}


def payload(result):
    assert isinstance(result, CallToolResult)
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content


def test_tools_registered_and_read_only():
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False


def test_get_full_raw_recipe_without_image_processing(mela_db, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Recipe tools must not decode images")
    monkeypatch.setattr(server.db, "get_recipe_image_bytes", forbidden)
    data = payload(server.get_recipe(1))
    assert data["ok"]
    recipe = data["recipe"]
    assert recipe["uuid"] == "u1"
    assert recipe["ingredients"] == "chicken, lemon, garlic"
    assert recipe["yield"] == "4"
    assert recipe["favorite"] is True
    assert recipe["want_to_cook"] is False
    assert recipe["prep_time"] == "10 min"
    assert recipe["image_count"] == 1
    assert "images" not in recipe
    assert payload(server.get_recipe("u1"))["recipe"] == recipe


def test_missing_recipe_is_structured_error(mela_db):
    result = server.get_recipe(999)
    assert result.is_error
    assert payload(result)["error"]["code"] == "recipe_not_found"


def test_list_wrappers_and_search(mela_db):
    assert payload(server.list_favorites())["recipes"][0]["id"] == 1
    assert payload(server.list_want_to_cook())["recipes"][0]["id"] == 2
    assert payload(server.search_recipes("kale sausage"))["total"] == 1
    assert payload(server.list_recipes(favorite=False))["total"] == 2
    data = payload(server.list_recipes(limit=2))
    assert data["total"] == 3 and data["next_offset"] == 2
    assert payload(server.list_recipes(offset=2))["next_offset"] is None
    assert {t["tag"] for t in payload(server.list_tags())["tags"]} == {"Dinner", "Comfort"}


def test_diagnostics(mela_db):
    data = payload(server.diagnose_library())
    assert data["ok"]
    assert data["counts"]["recipes"] == 3
    assert data["schema"]["compatible"]
    assert data["read_only"]


@pytest.mark.parametrize("name,args", [
    ("get_recipe", {"recipe_id": 1}), ("search_recipes", {"query": "chicken"}),
    ("list_recipes", {}), ("list_favorites", {}), ("list_want_to_cook", {}),
    ("list_tags", {}), ("diagnose_library", {}),
])
def test_actual_sdk_dispatch_returns_structured_json(mela_db, name, args):
    result = asyncio.run(server.mcp.call_tool(name, args))
    wire = result.model_dump(mode="json", by_alias=True)
    assert wire["structuredContent"]["ok"] is True
    assert json.loads(wire["content"][0]["text"]) == wire["structuredContent"]
    assert "base64" not in wire["content"][0]["text"]


def test_sdk_preserves_string_vs_numeric_id(mela_db):
    result = asyncio.run(server.mcp.call_tool("get_recipe", {"recipe_id": "1"}))
    assert payload(result)["error"]["code"] == "recipe_not_found"
    assert payload(asyncio.run(server.mcp.call_tool("get_recipe", {"recipe_id": "u1"})))["recipe"]["id"] == 1


def test_invalid_page_error_through_sdk(mela_db):
    result = asyncio.run(server.mcp.call_tool("list_recipes", {"limit": -1}))
    assert result.is_error
    assert payload(result)["error"]["code"] == "invalid_argument"


def test_missing_db_error(monkeypatch):
    monkeypatch.setenv("MELA_DB_PATH", "/no/such/Curcuma.sqlite")
    result = server.list_recipes()
    assert result.is_error
    assert payload(result)["error"]["code"] == "database_missing"
