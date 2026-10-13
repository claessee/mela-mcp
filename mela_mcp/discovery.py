"""Mela app/container discovery. Adapted from waynevernon/mela-cli (MIT).

See licenses/mela-cli-MIT.txt and THIRD_PARTY_NOTICES.md.
Discovery never opens SQLite or creates files in an app container.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping

EXPECTED_BUNDLE_ID = "recipes.mela.appkit"


@dataclass
class DiscoveryResult:
    app_path: Path | None = None
    app_path_source: str = "not found"
    bundle_id: str | None = None
    application_group: str | None = None
    db_path: Path | None = None
    db_path_source: str = "not found"
    support_dir: Path | None = None
    support_dir_source: str = "not found"
    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {key: str(value) if isinstance(value, Path) else value
                for key, value in asdict(self).items()}


def _run(args: list[str]) -> bytes:
    try:
        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.stdout if result.returncode == 0 else b""
    except (OSError, subprocess.SubprocessError):
        return b""


def read_bundle_id(app_path: Path) -> str | None:
    try:
        with (app_path / "Contents/Info.plist").open("rb") as handle:
            value = plistlib.load(handle).get("CFBundleIdentifier")
        return value if isinstance(value, str) else None
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        return None


def discover_app_path(home: Path) -> Path | None:
    for path in (Path("/Applications/Mela.app"), home / "Applications/Mela.app"):
        if read_bundle_id(path) == EXPECTED_BUNDLE_ID:
            return path
    if sys.platform == "darwin":
        output = _run(["mdfind", f'kMDItemCFBundleIdentifier == "{EXPECTED_BUNDLE_ID}"'])
        for name in sorted(output.decode("utf-8", "replace").splitlines()):
            path = Path(name)
            if read_bundle_id(path) == EXPECTED_BUNDLE_ID:
                return path
    return None


def read_application_groups(app_path: Path) -> list[str]:
    payload = _run(["codesign", "-d", "--entitlements", ":-", str(app_path)])
    starts = [offset for marker in (b"<?xml", b"<plist")
              if (offset := payload.find(marker)) >= 0]
    if not starts:
        return []
    try:
        groups = plistlib.loads(payload[min(starts):]).get("com.apple.security.application-groups", [])
    except (ValueError, plistlib.InvalidFileException, AttributeError):
        return []
    return [g for g in groups if isinstance(g, str) and "recipes.mela" in g
            and Path(g).name == g] if isinstance(groups, list) else []


def discover_mela(db_path: str | Path | None = None, *,
                  env: Mapping[str, str] | None = None,
                  home: Path | None = None) -> DiscoveryResult:
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    result = DiscoveryResult()
    override = db_path or env.get("MELA_DB_PATH", "").strip()
    # Explicit stores work without Mela installed, including test fixtures.
    if override:
        result.db_path = Path(override).expanduser().absolute()
        result.db_path_source = "argument" if db_path else "MELA_DB_PATH"
    else:
        app_override = env.get("MELA_APP_PATH", "").strip()
        result.app_path = Path(app_override).expanduser().absolute() if app_override else discover_app_path(home)
        result.app_path_source = "MELA_APP_PATH" if app_override else "auto-discovery"
        if result.app_path:
            result.bundle_id = read_bundle_id(result.app_path)
            if result.bundle_id != EXPECTED_BUNDLE_ID:
                result.errors.append({"code": "app_invalid", "message": "Configured app is not Mela.",
                                      "path": str(result.app_path)})
                return result
            groups = read_application_groups(result.app_path)
            if not groups:
                result.warnings.append("Could not read Mela's application-group entitlement; trying container discovery.")
            derived = [home / "Library/Group Containers" / g / "Data/Curcuma.sqlite" for g in groups]
        else:
            result.warnings.append("Mela app was not found; trying its locally synced Group Container.")
            derived = []
        try:
            existing = [p for p in derived if p.is_file()]
            if not existing:
                root = home / "Library/Group Containers"
                # Explicit iteration preserves permission errors (glob may suppress them).
                existing = sorted(p / "Data/Curcuma.sqlite" for p in root.iterdir()
                                  if "recipes.mela" in p.name and (p / "Data/Curcuma.sqlite").is_file()) if root.exists() else []
            existing = sorted(set(p.resolve() for p in existing))
            if len(existing) == 1:
                result.db_path = existing[0]
                result.db_path_source = "app entitlement" if existing[0] in [p.resolve() for p in derived] else "group container scan"
                result.application_group = result.db_path.parent.parent.name
            elif len(existing) > 1:
                result.errors.append({"code": "database_ambiguous", "message": "Multiple Mela stores found; set MELA_DB_PATH.",
                                      "paths": [str(p) for p in existing]})
        except OSError as exc:
            result.errors.append({"code": "access_denied", "message": str(exc)})
    if result.db_path:
        support_override = env.get("MELA_SUPPORT_DIR", "").strip()
        result.support_dir = (Path(support_override).expanduser().absolute() if support_override else
                              result.db_path.parent / ".Curcuma_SUPPORT/_EXTERNAL_DATA")
        result.support_dir_source = "MELA_SUPPORT_DIR" if support_override else "selected database sibling"
    return result
