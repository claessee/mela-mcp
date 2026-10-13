import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from mela_mcp import images
from mela_mcp.errors import MelaError

JPEG = b"\xff\xd8\xfftest-image"


def archive(image=JPEG):
    # Same NSKeyedArchiver CD_data shape inspected in mela-cli's fixture.
    return plistlib.dumps({"$objects": ["$null", {"NS.keys": [plistlib.UID(2)],
                                               "NS.objects": [plistlib.UID(3)]}, "CD_data", image]},
                         fmt=plistlib.FMT_BINARY)


def test_archive_image_extraction():
    assert images.extract_archive_image(archive()) == JPEG
    with pytest.raises(MelaError):
        images.extract_archive_image(b"not a plist")
    bad = plistlib.dumps({"$objects": [{"NS.keys": [plistlib.UID(999)], "NS.objects": [plistlib.UID(998)]}]}, fmt=plistlib.FMT_BINARY)
    with pytest.raises(MelaError):
        images.extract_archive_image(bad)


def test_raw_inline_archive_and_external_bytes(tmp_path):
    assert images.decode_image(JPEG, tmp_path) == JPEG
    assert images.decode_image(b"\x01" + JPEG, tmp_path) == JPEG
    assert images.decode_image(b"\x01" + archive(), tmp_path) == JPEG
    (tmp_path / "ABC123").write_bytes(JPEG)
    assert images.decode_image(b"\x02ABC123\x00", tmp_path) == JPEG


@pytest.mark.parametrize("ref", [b"../secret", b"/secret", b"..", b"\xffbad"])
def test_unsafe_references_rejected(tmp_path, ref):
    with pytest.raises(MelaError):
        images.decode_image(b"\x02" + ref + b"\x00", tmp_path)


def test_external_symlink_and_size_rejected(tmp_path):
    (tmp_path / "actual").write_bytes(JPEG)
    (tmp_path / "LINK").symlink_to(tmp_path / "actual")
    with pytest.raises(MelaError):
        images.decode_image(b"\x02LINK\x00", tmp_path)
    with pytest.raises(MelaError):
        images.decode_image(b"\x02actual\x00", tmp_path, max_bytes=10)


def test_compressed_external_image_decoded_only_in_private_directory(tmp_path, monkeypatch):
    (tmp_path / "COMPRESSED").write_bytes(b"bvx2placeholder")
    def fake_run(args, **kwargs):
        source = Path(args[args.index("-i") + 1])
        target = Path(args[args.index("-o") + 1])
        assert source.parent != tmp_path
        assert source.read_bytes() == b"bvx2placeholder"
        assert kwargs["timeout"] == 10
        target.write_bytes(archive())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(images.subprocess, "run", fake_run)
    assert images.decode_image(b"\x02COMPRESSED\x00", tmp_path) == JPEG


def test_decoder_unavailable_is_actionable(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("compression_tool")
    monkeypatch.setattr(images.subprocess, "run", missing)
    with pytest.raises(MelaError) as caught:
        images.decode_image(b"bvx2placeholder", tmp_path)
    assert caught.value.code == "image_unavailable"
