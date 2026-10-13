"""Opt-in live validation. No fixture substitutes for the local Mela library."""
import os
from contextlib import closing

import pytest

from mela_mcp import db, diagnostics

pytestmark = pytest.mark.skipif(os.environ.get("MELA_LIVE_TEST") != "1",
                               reason="Set MELA_LIVE_TEST=1 for live local Mela checks.")


def test_live_catalog_and_inspected_schema():
    report = diagnostics.diagnose_library()
    if report["errors"] and report["errors"][0]["code"] == "database_missing":
        pytest.skip("No local Mela installation/database was found; live verification unavailable.")
    assert report["ok"], report
    with closing(db.connect()) as conn:
        page = db.recipe_page(conn, limit=5)
        assert page["total"] == report["counts"]["recipes"]
        db.list_tags(conn)
        if page["recipes"]:
            first = page["recipes"][0]
            recipe = db.get_recipe(conn, first["id"])
            assert recipe["id"] == first["id"] and recipe["uuid"] == first["uuid"]
            assert {"ingredients", "instructions", "yield", "favorite", "want_to_cook"}.issubset(recipe)
