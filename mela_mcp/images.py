"""Optional blob decoding, adapted from waynevernon/mela-cli (MIT).

See licenses/mela-cli-MIT.txt and THIRD_PARTY_NOTICES.md. Not on the MCP text
read path. Errors here must not prevent access to ingredients/instructions.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path

from .errors import MelaError


def is_image(data: bytes) -> bool:
    return (data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")) or
            (data.startswith(b"RIFF") and data[8:12] == b"WEBP") or
            data[4:12] in {b"ftypheic", b"ftypheix", b"ftyphevc", b"ftyphevx", b"ftypmif1"})


def extract_archive_image(payload: bytes) -> bytes:
    try:
        archive = plistlib.loads(payload)
        objects = archive.get("$objects", [])
        def resolve(value):
            return objects[value.data] if isinstance(value, plistlib.UID) else value
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            keys, values = obj.get("NS.keys"), obj.get("NS.objects")
            if not isinstance(keys, list) or not isinstance(values, list):
                continue
            for key, value in zip(keys, values):
                if resolve(key) == "CD_data":
                    image = resolve(value)
                    if isinstance(image, bytes) and is_image(image):
                        return image
    except (ValueError, TypeError, IndexError, AttributeError, plistlib.InvalidFileException) as exc:
        raise MelaError("image_invalid", "Malformed keyed image archive.") from exc
    raise MelaError("image_invalid", "Image archive contains no recognized CD_data image.")


def decode_image(blob, support_dir: Path, *, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    if not isinstance(blob, (bytes, memoryview)) or not blob or len(blob) > max_bytes:
        raise MelaError("image_invalid", "Empty, oversized, or unsupported image blob.")
    data = bytes(blob)
    if data[0] == 1:
        data = data[1:]
    elif data[0] == 2:
        try:
            reference = data[1:].split(b"\x00", 1)[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise MelaError("image_invalid", "Non-ASCII external image reference.") from exc
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", reference):
            raise MelaError("image_invalid", "Unsafe external image reference.")
        path = support_dir / reference
        try:
            if path.is_symlink() or path.resolve().parent != support_dir.resolve():
                raise MelaError("image_invalid", "External image symlinks are not supported.")
            with path.open("rb") as handle:
                data = handle.read(max_bytes + 1)
        except OSError as exc:
            raise MelaError("image_unavailable", "External image cannot be read.", reference=reference) from exc
        if len(data) > max_bytes:
            raise MelaError("image_invalid", "External image exceeds size limit.")
    if is_image(data):
        return data
    if data.startswith(b"bvx2"):
        # Only private copies are passed to a decoder. The CLI never touches Mela.
        with tempfile.TemporaryDirectory(prefix="mela-image-") as directory:
            source, target = Path(directory) / "source", Path(directory) / "decoded"
            source.write_bytes(data)
            try:
                proc = subprocess.run([os.environ.get("MELA_COMPRESSION_TOOL", "compression_tool"),
                                       "-decode", "-a", "lzfse", "-i", str(source), "-o", str(target)],
                                      capture_output=True, timeout=10)
                if proc.returncode != 0:
                    raise MelaError("image_invalid", "LZFSE decoder failed.")
                with target.open("rb") as handle:
                    data = handle.read(max_bytes + 1)
            except (OSError, subprocess.SubprocessError) as exc:
                raise MelaError("image_unavailable", "LZFSE decoder is unavailable or timed out.") from exc
        if len(data) > max_bytes:
            raise MelaError("image_invalid", "Decoded archive exceeds size limit.")
    return extract_archive_image(data)
