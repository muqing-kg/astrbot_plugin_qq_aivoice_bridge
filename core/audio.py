"""Audio sniffing, conversion, and a bounded in-memory voice cache."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
import time
import wave
from collections import OrderedDict
from pathlib import Path

from astrbot.api import logger

SUPPORTED_FORMATS = {"silk", "wav", "mp3"}

SILK_MAGIC = b"#!SILK_V3"

# The cache lives in process memory only. Long-running deployments must not be
# able to grow it without bound, so every dimension has a hard ceiling.
VOICE_CACHE_MAX_ENTRIES = 128
VOICE_CACHE_MAX_BYTES = 32 * 1024 * 1024
VOICE_CACHE_TTL = 3600


def sniff_audio_format(data: bytes) -> str:
    if not data:
        return "bin"
    if is_silk(data):
        return "silk"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3"):
        return "mp3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        # MPEG audio sets the layer bits; ADTS (AAC) leaves them at zero.
        return "aac" if (data[1] & 0x06) == 0 else "mp3"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"fLaC"):
        return "flac"
    return "bin"


def is_silk(data: bytes) -> bool:
    """Detect a Tencent SILK payload.

    QQ ships two header layouts for the same codec: ``\\x02#!SILK_V3`` and
    ``\\x03#!SILK_V3``, plus a bare ``#!SILK_V3`` form.
    """
    if data.startswith(SILK_MAGIC):
        return True
    return len(data) >= 10 and data[1:10] == SILK_MAGIC


def normalize_silk(data: bytes) -> bytes:
    """Rewrite the SILK marker to the canonical ``\\x02`` form.

    QQ prepends a single marker byte that is ``0x02`` in most builds and
    ``0x03`` in others. pysilk rejects anything but ``0x02``, and ffmpeg cannot
    read SILK at all, so whatever marker arrives is normalised before the
    payload is decoded or handed downstream.
    """
    if data[:1] == b"\x02":
        return data
    if data[:1] and data[1:10] == SILK_MAGIC:
        return b"\x02" + data[1:]
    return data


def purge_legacy_cache_dir(data_dir: Path) -> bool:
    """Delete the on-disk audio cache directory left by earlier versions."""
    legacy = Path(data_dir) / "cache"
    if not legacy.is_dir():
        return False
    shutil.rmtree(legacy, ignore_errors=True)
    return True


class VoiceCache:
    """LRU cache of generated audio bytes that never touches the disk.

    Bounded by entry count, total bytes and entry age, so a process that runs
    for months holds at most ``max_bytes`` of audio. Expiry and eviction happen
    inline on read/write; no timers, threads or background tasks are created.
    """

    def __init__(
        self,
        *,
        max_entries: int = VOICE_CACHE_MAX_ENTRIES,
        max_bytes: int = VOICE_CACHE_MAX_BYTES,
        ttl: int = VOICE_CACHE_TTL,
    ):
        self._items: OrderedDict[str, tuple[bytes, str, float]] = OrderedDict()
        self._max_entries = max(1, int(max_entries))
        self._max_bytes = max(0, int(max_bytes))
        self._ttl = max(0, int(ttl))
        self._bytes = 0

    @staticmethod
    def cache_key(character_id: str, output_format: str, text: str) -> str:
        raw = f"{character_id}\0{output_format}\0{text}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str) -> tuple[bytes, str] | None:
        item = self._items.get(key)
        if item is None:
            return None
        data, fmt, stored_at = item
        if self._ttl > 0 and time.time() - stored_at > self._ttl:
            self._drop(key)
            return None
        self._items.move_to_end(key)
        return data, fmt

    def put(self, key: str, data: bytes, fmt: str) -> None:
        if not data:
            return
        self._drop(key)
        self._items[key] = (bytes(data), str(fmt), time.time())
        self._bytes += len(data)
        self._evict()

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0

    def _drop(self, key: str) -> None:
        item = self._items.pop(key, None)
        if item is not None:
            self._bytes -= len(item[0])

    def _evict(self) -> None:
        if self._ttl > 0:
            now = time.time()
            stale = [k for k, v in self._items.items() if now - v[2] > self._ttl]
            for key in stale:
                self._drop(key)
        while self._items and (
            len(self._items) > self._max_entries or self._bytes > self._max_bytes
        ):
            key, item = self._items.popitem(last=False)
            self._bytes -= len(item[0])


# One conversion handles a few seconds of audio; anything longer is a hung
# ffmpeg, and giving up frees the worker thread and the temp directory.
FFMPEG_TIMEOUT = 60.0


class AudioConverter:
    def __init__(
        self,
        temp_dir: Path,
        *,
        ffmpeg_path: str = "ffmpeg",
        timeout: float = FFMPEG_TIMEOUT,
    ):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = ffmpeg_path or "ffmpeg"
        self.timeout = max(1.0, float(timeout))

    def purge_temp_files(self) -> int:
        """Delete audio files left behind by a crash or an unclean shutdown."""
        removed = 0
        for path in self.temp_dir.glob("*"):
            try:
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def new_temp_path(self, fmt: str) -> Path:
        suffix = str(fmt or "bin").lower()
        return self.temp_dir / f"qq_aivoice_{time.time_ns()}.{suffix}"

    async def convert(
        self,
        data: bytes,
        target_format: str,
        *,
        source_format: str | None = None,
    ) -> tuple[bytes, str]:
        target = str(target_format or "wav").lower()
        source = source_format or sniff_audio_format(data)
        if target not in SUPPORTED_FORMATS:
            target = "wav"
        if source == target:
            return (normalize_silk(data) if target == "silk" else data), source
        return await asyncio.to_thread(self._convert_sync, data, source, target)

    def _convert_sync(self, data: bytes, source: str, target: str) -> tuple[bytes, str]:
        try:
            wav_data = data
            if target == "silk":
                if source == "silk":
                    return data, "silk"
                if source != "wav":
                    wav_data = self._to_wav(data, source)
                return self._wav_to_silk(wav_data), "silk"

            if target == "wav":
                if source == "wav":
                    return data, "wav"
                if source == "silk":
                    return self._silk_to_wav(data), "wav"
                return self._ffmpeg_to_wav(data, source), "wav"

            if target == "mp3":
                if source == "mp3":
                    return data, "mp3"
                if source != "wav":
                    wav_data = self._to_wav(data, source)
                return self._ffmpeg_to_mp3(wav_data), "mp3"
        except Exception as e:
            logger.warning(
                "[QQ声聊] 音频转换失败 %s -> %s: %s",
                source,
                target,
                e,
            )
            if target == "mp3" and source in {"wav", "silk"}:
                try:
                    wav_data = data if source == "wav" else self._silk_to_wav(data)
                    return wav_data, "wav"
                except Exception as fallback_error:  # noqa: BLE001
                    logger.warning(
                        "[QQ声聊] 转换失败后回退 WAV 也失败了: %s",
                        fallback_error,
                    )
            # Never hand back the untouched payload as if it were ``target``;
            # callers send whatever comes out of here, so a silent pass-through
            # turns into a broken voice message downstream.
            raise

    def _to_wav(self, data: bytes, source: str) -> bytes:
        if source == "silk":
            return self._silk_to_wav(data)
        return self._ffmpeg_to_wav(data, source)

    @staticmethod
    def _silk_to_wav(data: bytes) -> bytes:
        import io

        import pysilk

        pcm = io.BytesIO()
        pysilk.decode(io.BytesIO(normalize_silk(data)), pcm, sample_rate=24000)
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "NONE"))
            wav.writeframes(pcm.getvalue())
        return out.getvalue()

    @staticmethod
    def _wav_to_silk(data: bytes) -> bytes:
        import io

        import pysilk

        with wave.open(io.BytesIO(data), "rb") as wav:
            rate = wav.getframerate()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())
        if channels != 1 or width != 2 or rate not in {8000, 12000, 16000, 24000}:
            data = AudioConverter._normalize_wav(data)
            with wave.open(io.BytesIO(data), "rb") as wav:
                rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        out = io.BytesIO()
        pysilk.encode(
            io.BytesIO(frames),
            out,
            sample_rate=rate,
            bit_rate=24000,
            max_internal_sample_rate=min(rate, 24000),
            tencent=True,
        )
        return out.getvalue()

    @staticmethod
    def _normalize_wav(data: bytes) -> bytes:
        import io

        with wave.open(io.BytesIO(data), "rb") as src:
            params = src.getparams()
            frames = src.readframes(src.getnframes())
        if params.nchannels == 2 and params.sampwidth == 2:
            import array

            samples = array.array("h", frames)
            mono = array.array(
                "h",
                (
                    int((samples[i] + samples[i + 1]) / 2)
                    for i in range(0, len(samples), 2)
                ),
            )
            frames = mono.tobytes()
            params = (1, 2, params.framerate, len(mono), "NONE", "not compressed")
        out = io.BytesIO()
        with wave.open(out, "wb") as dst:
            dst.setparams((1, 2, params[2], 0, "NONE", "NONE"))
            dst.writeframes(frames)
        return out.getvalue()

    def _ffmpeg_to_wav(self, data: bytes, source: str) -> bytes:
        return self._ffmpeg(data, source, "wav")

    def _ffmpeg_to_mp3(self, data: bytes) -> bytes:
        return self._ffmpeg(data, "wav", "mp3")

    def _ffmpeg(self, data: bytes, source: str, target: str) -> bytes:
        if not shutil.which(self.ffmpeg_path) and self.ffmpeg_path == "ffmpeg":
            raise RuntimeError("ffmpeg not found")
        with tempfile.TemporaryDirectory(prefix="qq_aivoice_") as tmp:
            in_path = Path(tmp) / f"input.{source}"
            out_path = Path(tmp) / f"output.{target}"
            in_path.write_bytes(data)
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(in_path),
            ]
            if target == "wav":
                cmd += ["-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le"]
            elif target == "mp3":
                cmd += ["-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-q:a", "5"]
            cmd.append(str(out_path))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=self.timeout,
            )
            if proc.returncode != 0 or not out_path.exists():
                raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore")[:300])
            return out_path.read_bytes()
