import os
import sqlite3
import pytest
from mela_mcp import db

def test_get_db_path_honors_env(mela_db):
    assert db.get_db_path() == mela_db

def test_get_db_path_missing_raises(monkeypatch):
    monkeypatch.setenv("MELA_DB_PATH", "/no/such/Curcuma.sqlite")
    with pytest.raises(FileNotFoundError) as e:
        db.get_db_path()
    assert "MELA_DB_PATH" in str(e.value)

def test_connect_is_read_only(mela_db):
    conn = db.connect()
    assert conn.execute("SELECT count(*) FROM ZRECIPEOBJECT").fetchone()[0] == 3
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("INSERT INTO ZRECIPETAG (Z_PK, ZTITLE) VALUES (99, 'x')")

def test_list_tags_counts(mela_db):
    conn = db.connect()
    tags = db.list_tags(conn)
    by_name = {t["tag"]: t["count"] for t in tags}
    assert by_name == {"Dinner": 2, "Comfort": 1}
    # sorted: Dinner (2) before Comfort (1)
    assert [t["tag"] for t in tags] == ["Dinner", "Comfort"]

def test_get_recipe_full(mela_db):
    conn = db.connect()
    r = db.get_recipe(conn, 1)
    assert r["id"] == 1
    assert r["title"] == "Lemon Chicken"
    assert r["ingredients"] == "chicken, lemon, garlic"
    assert r["favorite"] is True
    assert r["want_to_cook"] is False
    assert r["tags"] == ["Dinner"]
    assert r["description"] == "Mains"
    assert r["date_added"].startswith("2023-")  # 700000000s after 2001

def test_get_recipe_tags_multi(mela_db):
    conn = db.connect()
    r = db.get_recipe(conn, 2)
    assert r["tags"] == ["Comfort", "Dinner"]  # sorted

def test_get_recipe_missing_returns_none(mela_db):
    conn = db.connect()
    assert db.get_recipe(conn, 999) is None

def test_search_single_term_across_columns(mela_db):
    conn = db.connect()
    hits = db.search_recipes(conn, "chicken")
    assert [h["title"] for h in hits] == ["Lemon Chicken"]
    assert hits[0]["id"] == 1
    assert "chicken" in hits[0]["snippet"].lower()

def test_search_multi_term_all_must_match(mela_db):
    conn = db.connect()
    # "kale sausage" both in recipe 2's ingredients
    assert [h["id"] for h in db.search_recipes(conn, "kale sausage")] == [2]
    # "kale chocolate" appears in no single recipe
    assert db.search_recipes(conn, "kale chocolate") == []

def test_search_filter_favorite(mela_db):
    conn = db.connect()
    assert [h["id"] for h in db.search_recipes(conn, "it", favorite=True)] == [1]

def test_search_filter_tag(mela_db):
    conn = db.connect()
    ids = sorted(h["id"] for h in db.search_recipes(conn, "it", tag="Dinner"))
    assert ids == [1, 2]

def test_search_limit(mela_db):
    conn = db.connect()
    assert len(db.search_recipes(conn, "it", limit=1)) == 1
