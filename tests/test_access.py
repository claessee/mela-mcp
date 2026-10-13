import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from mela_mcp import db, diagnostics, snapshot
from mela_mcp.errors import MelaError


def mutate(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(sql)
        conn.commit()


def test_source_files_unchanged_and_private_files_cleaned(mela_db):
    source = Path(mela_db)
    before = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
              for p in source.parent.iterdir() if p.is_file()}
    with closing(db.connect()) as conn:
        private = Path(conn.snapshot_directory.name)
        assert private != source.parent
        db.recipe_page(conn)
        db.get_recipe(conn, "u2")
        db.list_tags(conn)
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    assert not private.exists()
    after = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
             for p in source.parent.iterdir() if p.is_file()}
    assert before == after


@pytest.mark.parametrize("sql", [
    "UPDATE ZRECIPEOBJECT SET ZTITLE='bad'", "DELETE FROM ZRECIPEOBJECT",
    "CREATE TABLE bad(x)", "CREATE TEMP TABLE bad(x)", "DROP TABLE ZRECIPETAG",
    "ATTACH DATABASE ':memory:' AS other", "PRAGMA query_only=OFF", "VACUUM",
    "PRAGMA journal_mode=DELETE", "PRAGMA wal_checkpoint(TRUNCATE)",
])
def test_sql_writes_and_escapes_denied(mela_db, sql):
    with closing(db.connect()) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)


def test_committed_wal_is_visible_and_source_sidecars_unchanged(mela_db):
    with closing(sqlite3.connect(mela_db)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE ZRECIPEOBJECT SET ZTITLE='Latest WAL title' WHERE Z_PK=1")
        writer.commit()
        paths = [Path(mela_db + suffix) for suffix in ("", "-wal", "-shm")]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        with closing(db.connect()) as reader:
            assert db.get_recipe(reader, 1)["title"] == "Latest WAL title"
        assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


def test_numbered_tag_join_adapts_from_inspected_schema(mela_db):
    mutate(mela_db, "ALTER TABLE Z_4TAGS RENAME TO Z_8TAGS; "
                   "ALTER TABLE Z_8TAGS RENAME COLUMN Z_4RECIPES TO Z_8RECIPES; "
                   "ALTER TABLE Z_8TAGS RENAME COLUMN Z_5TAGS TO Z_9TAGS;")
    with closing(db.connect()) as conn:
        assert conn.schema.join_table == "Z_8TAGS"
        assert db.get_recipe(conn, 2)["tags"] == ["Comfort", "Dinner"]
        assert db.recipe_page(conn, tag="Comfort")["total"] == 1


def test_ambiguous_relationship_fails_closed(mela_db):
    mutate(mela_db, "CREATE TABLE Z_9TAGS(Z_9RECIPES INTEGER, Z_10TAGS INTEGER);")
    with closing(db.connect()) as conn:
        with pytest.raises(MelaError, match="ambiguous") as caught:
            db.list_tags(conn)
        assert caught.value.code == "schema_unsupported"
    assert not diagnostics.diagnose_library()["ok"]


def test_missing_essential_field_reported(mela_db):
    mutate(mela_db, "ALTER TABLE ZRECIPEOBJECT RENAME COLUMN ZINGREDIENTS TO ZNEWINGREDIENTS;")
    report = diagnostics.diagnose_library()
    assert not report["ok"]
    assert "ZRECIPEOBJECT.ZINGREDIENTS" in report["schema"]["missing"]
    assert report["errors"][0]["code"] == "schema_unsupported"


def test_optional_images_and_date_do_not_break_catalog(mela_db):
    mutate(mela_db, "DROP TABLE ZRECIPEIMAGEOBJECT; ALTER TABLE ZRECIPEOBJECT DROP COLUMN ZDATE;")
    with closing(db.connect()) as conn:
        recipe = db.get_recipe(conn, 1)
        assert recipe["image_count"] is None and recipe["date_added"] is None
        assert len(conn.schema.warnings) == 2
    assert diagnostics.diagnose_library()["ok"]


def test_exact_ids_no_fuzzy_selection(mela_db):
    with closing(db.connect()) as conn:
        assert db.get_recipe(conn, "u1")["id"] == 1
        assert db.get_recipe(conn, "u") is None
        assert db.get_recipe(conn, "Lemon Chicken") is None
        assert db.get_recipe(conn, "1") is None
    mutate(mela_db, "UPDATE ZRECIPEOBJECT SET ZID='u1' WHERE Z_PK=2;")
    with closing(db.connect()) as conn:
        with pytest.raises(MelaError) as caught:
            db.get_recipe(conn, "u1")
        assert caught.value.code == "recipe_ambiguous"


def test_stable_pagination_and_batched_tags(mela_db):
    mutate(mela_db, "UPDATE ZRECIPEOBJECT SET ZTITLE='Same';")
    with closing(db.connect()) as conn:
        statements = []
        conn.set_trace_callback(statements.append)
        page = db.recipe_page(conn, limit=2)
        assert [r["id"] for r in page["recipes"]] == [1, 2]
        assert page["next_offset"] == 2
        assert len(statements) == 3  # count + summary page + single tag batch
        assert db.recipe_page(conn, offset=2)["recipes"][0]["id"] == 3
        assert db.recipe_page(conn, offset=20)["recipes"] == []


def test_literal_search_unicode_and_null_false(mela_db):
    mutate(mela_db, "UPDATE ZRECIPEOBJECT SET ZTITLE='Straße 100%_special', ZFAVORITE=NULL WHERE Z_PK=1;")
    with closing(db.connect()) as conn:
        assert db.search_recipes(conn, "STRASSE")[0]["id"] == 1
        assert db.search_recipes(conn, "%_special")[0]["id"] == 1
        assert db.search_recipes(conn, "%nosuch") == []
        assert db.recipe_page(conn, favorite=False)["total"] == 3


def test_tag_counts_ignore_dangling_and_duplicate_relationships(mela_db):
    mutate(mela_db, "INSERT INTO Z_4TAGS VALUES (999,10); INSERT INTO Z_4TAGS VALUES (1,10);")
    with closing(db.connect()) as conn:
        assert db.list_tags(conn)[0] == {"tag": "Dinner", "count": 2}
        assert db.get_recipe(conn, 1)["tags"] == ["Dinner"]


@pytest.mark.parametrize("limit,offset", [(0,0), (-1,0), (101,0), (True,0), (1,-1)])
def test_invalid_paging_rejected(mela_db, limit, offset):
    with closing(db.connect()) as conn:
        with pytest.raises(MelaError) as caught:
            db.recipe_page(conn, limit=limit, offset=offset)
        assert caught.value.code == "invalid_argument"


def test_changing_snapshot_retries_then_fails_without_source_writes(mela_db, monkeypatch):
    original = snapshot._fingerprint
    calls = []
    def changing(path):
        value = original(path)
        calls.append(path)
        return value + (len(calls),) if value else value
    monkeypatch.setattr(snapshot, "_fingerprint", changing)
    with pytest.raises(MelaError) as caught:
        db.connect()
    assert caught.value.code == "database_busy"
    assert len(calls) == 18


def test_rollback_journal_rejected(mela_db):
    Path(mela_db + "-journal").write_bytes(b"pending")
    with pytest.raises(MelaError) as caught:
        db.connect()
    assert caught.value.code == "database_busy"


def test_invalid_db_diagnostic(tmp_path, monkeypatch):
    path = tmp_path / "bad.sqlite"
    path.write_bytes(b"not SQLite")
    monkeypatch.setenv("MELA_DB_PATH", str(path))
    report = diagnostics.diagnose_library()
    assert not report["ok"]
    assert report["errors"][0]["code"] == "database_invalid"


def test_path_with_uri_characters(mela_db):
    source = Path(mela_db)
    target = source.parent / "Mela ?#% å.sqlite"
    target.write_bytes(source.read_bytes())
    with closing(db.connect(target)) as conn:
        assert db.get_recipe(conn, 1)["uuid"] == "u1"
