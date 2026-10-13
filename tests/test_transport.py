"""Exercise the real stdio server process, initialization, discovery and calls."""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def test_stdio_agent_workflow(mela_db):
    async def run():
        parameters = StdioServerParameters(command=sys.executable,
                                           args=["-m", "mela_mcp.server"],
                                           cwd=Path(__file__).resolve().parents[1],
                                           env={**os.environ, "MELA_DB_PATH": mela_db})
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {"list_recipes", "get_recipe", "diagnose_library"} <= {t.name for t in tools.tools}
                favorites = await session.call_tool("list_favorites", {"limit": 1})
                assert favorites.structured_content["ok"]
                item = favorites.structured_content["recipes"][0]
                full = await session.call_tool("get_recipe", {"recipe_id": item["uuid"]})
                assert full.structured_content["recipe"]["ingredients"] == "chicken, lemon, garlic"
                error = await session.call_tool("get_recipe", {"recipe_id": 999})
                assert error.is_error and error.structured_content["error"]["code"] == "recipe_not_found"
                doctor = await session.call_tool("diagnose_library", {})
                assert doctor.structured_content["counts"]["recipes"] == 3
                wrong_type = await session.call_tool("list_recipes", {"limit": True})
                assert wrong_type.is_error  # A boolean must never silently become page size 1.
    asyncio.run(run())
