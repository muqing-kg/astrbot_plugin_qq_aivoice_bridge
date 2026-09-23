import asyncio

import pytest

from core.audio import (
    SILK_MAGIC,
    AudioConverter,
    VoiceCache,
    normalize_silk,
    purge_legacy_cache_dir,
    sniff_audio_format,
)

# First 16 bytes captured from a live QQ AI voice download.
QQ_SILK_HEAD = bytes.fromhex("03 23 21 53 49 4c 4b 5f 56 33 23 00 eb 04 6d 38")


def test_sniff_common_formats():
    assert sniff_audio_format(b"\x02#!SILK_V3....") == "silk"
    assert sniff_audio_format(b"#!SILK_V3....") == "silk"
    assert sniff_audio_format(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert sniff_audio_format(b"ID3\x04\x00\x00") == "mp3"
    assert sniff_audio_format(b"\xff\xfb\x90\x00") == "mp3"
    assert sniff_audio_format(b"OggS....") == "ogg"


def test_unknown_format():
    assert sniff_audio_format(b"not-audio") == "bin"


def test_voice_cache_returns_until_ttl_expires():
    cache = VoiceCache(ttl=60)
    key = cache.cache_key("role", "wav", "你好")
    cache.put(key, b"audio", "wav")
    assert cache.get(key) == (b"audio", "wav")
    assert cache.get("missing") is None


def test_voice_cache_drops_expired_entries(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr("core.audio.time.time", lambda: now["t"])
    cache = VoiceCache(ttl=10)
    cache.put("k", b"audio", "wav")
    now["t"] = 1011.0
    assert cache.get("k") is None


def test_voice_cache_evicts_least_recently_used():
    cache = VoiceCache(max_entries=2, max_bytes=1024, ttl=60)
    for key in ("a", "b", "c"):
        cache.put(key, b"1234", "wav")
    assert cache.get("a") is None
    assert cache.get("b") == (b"1234", "wav")
    assert cache.get("c") == (b"1234", "wav")


def test_voice_cache_respects_byte_budget():
    cache = VoiceCache(max_entries=10, max_bytes=5, ttl=60)
    cache.put("a", b"1234", "wav")
    cache.put("b", b"1234", "wav")
    assert cache.get("a") is None
    assert cache.get("b") is not None


def test_temp_files_are_purged_on_startup(tmp_path):
    converter = AudioConverter(tmp_path / "temp")
    path = converter.new_temp_path("wav")
    path.write_bytes(b"x")
    assert converter.purge_temp_files() == 1
    assert not path.exists()


def test_legacy_cache_dir_is_removed(tmp_path):
    legacy = tmp_path / "cache"
    legacy.mkdir()
    (legacy / "old.wav").write_bytes(b"x")
    assert purge_legacy_cache_dir(tmp_path) is True
    assert not legacy.exists()
    assert purge_legacy_cache_dir(tmp_path) is False


def test_convert_raises_when_payload_cannot_be_converted(tmp_path):
    """A payload ffmpeg cannot decode must fail, not silently pass through."""
    converter = AudioConverter(tmp_path / "temp")
    with pytest.raises(RuntimeError):
        asyncio.run(
            converter.convert(b"this is not audio at all", "wav", source_format="bin")
        )


def test_convert_short_circuits_when_format_matches(tmp_path):
    converter = AudioConverter(tmp_path / "temp")
    payload = b"\x02#!SILK_V3fake"
    data, fmt = asyncio.run(
        converter.convert(payload, "silk", source_format="silk")
    )
    assert data == payload
    assert fmt == "silk"


def test_qq_silk_header_is_recognised():
    """QQ sends a 0x03 marker; only 0x02 used to be accepted."""
    assert sniff_audio_format(QQ_SILK_HEAD) == "silk"


def test_silk_marker_is_normalised_to_0x02():
    assert normalize_silk(QQ_SILK_HEAD)[:10] == bytes.fromhex(
        "02 23 21 53 49 4c 4b 5f 56 33"
    )
    assert normalize_silk(b"\x02" + SILK_MAGIC + b"rest") == b"\x02" + SILK_MAGIC + b"rest"
    assert normalize_silk(SILK_MAGIC + b"rest") == SILK_MAGIC + b"rest"


def test_passthrough_silk_is_normalised(tmp_path):
    converter = AudioConverter(tmp_path / "temp")
    payload = QQ_SILK_HEAD + b"x" * 32
    data, fmt = asyncio.run(converter.convert(payload, "silk", source_format="silk"))
    assert fmt == "silk"
    assert data[:10] == bytes.fromhex("02 23 21 53 49 4c 4b 5f 56 33")

