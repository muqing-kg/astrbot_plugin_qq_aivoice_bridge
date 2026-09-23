"""Audio sniffing, conversion, and byte cache."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger("astrbot")


SUPPORTED_FORMATS = {"silk", "wav", "mp3"}


def sniff_audio_format(data: bytes) -> str:
    if not data:
        return "bin"
    if data.startswith((b"\x02#!SILK_V3", b"#!SILK_V3")):
        return "silk"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3"):
        return "mp3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"fLaC"):
        return "flac"
    return "bin"


class AudioConverter:
    def __init__(
        self,
        cache_dir: Path,
        *,
        ffmpeg_path: str = "ffmpeg",
        cache_ttl: int = 86400,
        max_cache_mb: int = 200,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = ffmpeg_path or "ffmpeg"
        self.cache_ttl = max(0, int(cache_ttl))
        self.max_cache_bytes = max(0, int(max_cache_mb)) * 1024 * 1024

    def cache_key(self, character_id: str, output_format: str, text: str) -> str:
        raw = f"{character_id}\0{output_format}\0{text}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get_cache(self, key: str) -> tuple[bytes, str] | None:
        if self.cache_ttl <= 0:
            return None
        for path in self.cache_dir.glob(f"{key}.*"):
            try:
                if time.time() - path.stat().st_mtime > self.cache_ttl:
                    path.unlink(missing_ok=True)
                    continue
                fmt = path.suffix.lstrip(".").lower()
                return path.read_bytes(), fmt
            except OSError:
                continue
        return None

    def put_cache(self, key: str, data: bytes, fmt: str) -> Path:
        path = self.cache_dir / f"{key}.{fmt}"
        path.write_bytes(data)
        self.cleanup()
        return path

    def cleanup(self) -> None:
        if self.cache_ttl > 0:
            now = time.time()
            for path in list(self.cache_dir.glob("*")):
                try:
                    if now - path.stat().st_mtime > self.cache_ttl:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        if self.max_cache_bytes <= 0:
            return
        files = []
        total = 0
        for path in self.cache_dir.glob("*"):
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        if total <= self.max_cache_bytes:
            return
        for _, size, path in sorted(files):
            if total <= self.max_cache_bytes:
                break
            try:
                path.unlink(missing_ok=True)
                total -= size
            except OSError:
                continue

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
            return data, source
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
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "QQ AIVoice: conversion failed %s -> %s: %s",
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
                        "QQ AIVoice: WAV fallback failed: %s",
                        fallback_error,
                    )
        return data, source

    def _to_wav(self, data: bytes, source: str) -> bytes:
        if source == "silk":
            return self._silk_to_wav(data)
        return self._ffmpeg_to_wav(data, source)

    @staticmethod
    def _silk_to_wav(data: bytes) -> bytes:
        import io

        import pysilk

        pcm = io.BytesIO()
        pysilk.decode(io.BytesIO(data), pcm, sample_rate=24000)
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
            proc = subprocess.run(cmd, capture_output=True, check=False)
            if proc.returncode != 0 or not out_path.exists():
                raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore")[:300])
            return out_path.read_bytes()
