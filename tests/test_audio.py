from core.audio import (
    AudioConverter,
    VoiceCache,
    purge_legacy_cache_dir,
    sniff_audio_format,
)


def test_sniff_common_formats():
    assert sniff_audio_format(b"\x02#!SILK_V3....") == "silk"
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

