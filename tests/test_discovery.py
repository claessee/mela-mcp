import plistlib
from pathlib import Path

from mela_mcp import discovery, diagnostics, server


def fixture_app(home, group="NEWTEAM.recipes.mela"):
    app = home / "Applications/Mela.app"
    info = app / "Contents/Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(plistlib.dumps({"CFBundleIdentifier": discovery.EXPECTED_BUNDLE_ID}))
    store = home / "Library/Group Containers" / group / "Data/Curcuma.sqlite"
    store.parent.mkdir(parents=True)
    store.touch()
    return app, store


def test_entitlement_discovery(tmp_path, monkeypatch):
    app, store = fixture_app(tmp_path)
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: app)
    monkeypatch.setattr(discovery, "read_application_groups", lambda app: ["NEWTEAM.recipes.mela"])
    result = discovery.discover_mela(env={}, home=tmp_path)
    assert result.db_path == store
    assert result.db_path_source == "app entitlement"
    assert result.support_dir == store.parent / ".Curcuma_SUPPORT/_EXTERNAL_DATA"


def test_container_fallback(tmp_path, monkeypatch):
    _, store = fixture_app(tmp_path)
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: None)
    result = discovery.discover_mela(env={}, home=tmp_path)
    assert result.db_path == store
    assert result.db_path_source == "group container scan"


def test_explicit_db_controls_support_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: (_ for _ in ()).throw(AssertionError("Do not discover app for explicit DB")))
    actual = tmp_path / "custom/store.sqlite"
    result = discovery.discover_mela(env={"MELA_DB_PATH": str(actual), "MELA_APP_PATH": "/wrong/app"}, home=tmp_path)
    assert result.db_path == actual
    assert result.support_dir == actual.parent / ".Curcuma_SUPPORT/_EXTERNAL_DATA"
    result = discovery.discover_mela(tmp_path / "argument.sqlite", env={"MELA_DB_PATH": str(actual), "MELA_SUPPORT_DIR": str(tmp_path / "images")})
    assert result.db_path_source == "argument"
    assert result.support_dir == tmp_path / "images"


def test_multiple_stores_are_ambiguous(tmp_path, monkeypatch):
    fixture_app(tmp_path)
    second = tmp_path / "Library/Group Containers/OTHER.recipes.mela/Data/Curcuma.sqlite"
    second.parent.mkdir(parents=True)
    second.touch()
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: None)
    result = discovery.discover_mela(env={}, home=tmp_path)
    assert result.db_path is None
    assert result.errors[0]["code"] == "database_ambiguous"


def test_empty_env_does_not_inherit_process_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MELA_DB_PATH", "/unwanted/path")
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: None)
    assert discovery.discover_mela(env={}, home=tmp_path).db_path is None


def test_invalid_configured_app(tmp_path):
    result = discovery.discover_mela(env={"MELA_APP_PATH": str(tmp_path / "Missing.app")}, home=tmp_path)
    assert result.errors[0]["code"] == "app_invalid"
    assert result.db_path is None


def test_container_permission_error_is_visible(tmp_path, monkeypatch):
    root = tmp_path / "Library/Group Containers"
    root.mkdir(parents=True)
    monkeypatch.setattr(discovery, "discover_app_path", lambda home: None)
    original = Path.iterdir
    def denied(path):
        if path == root:
            raise PermissionError("test access denied")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", denied)
    result = discovery.discover_mela(env={}, home=tmp_path)
    assert result.errors[0]["code"] == "access_denied"


def test_permission_error_in_snapshot_is_structured(mela_db, monkeypatch):
    from mela_mcp import db
    def denied(source):
        raise PermissionError("test access denied")
    monkeypatch.setattr(db, "copy_snapshot", denied)
    report = diagnostics.diagnose_library()
    assert report["errors"][0]["code"] == "access_denied"
    result = server.list_recipes()
    assert result.is_error
    assert result.structured_content["error"]["code"] == "access_denied"


def test_entitlement_xml_parser(monkeypatch, tmp_path):
    payload = plistlib.dumps({"com.apple.security.application-groups": ["TEAM.recipes.mela", "other", "../../recipes.mela"]})
    monkeypatch.setattr(discovery, "_run", lambda args: payload)
    assert discovery.read_application_groups(tmp_path) == ["TEAM.recipes.mela"]
