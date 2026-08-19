"""Utilities for preparing, publishing, and binding real voice references."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import numpy as np
import requests
import soundfile as sf


TARGET_SAMPLE_RATE = 24000
MIN_REFERENCE_SECONDS = 3.0
MAX_REFERENCE_SECONDS = 30.0


class VoiceProfileError(RuntimeError):
    """Raised when a reference cannot safely become a voice profile."""


@dataclass(frozen=True)
class AudioMetrics:
    duration_seconds: float
    sample_rate: int
    channels: int
    peak_dbfs: float
    rms_dbfs: float
    clipping_ratio: float
    silence_ratio: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_reference(path: Path) -> AudioMetrics:
    try:
        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        raise VoiceProfileError(f"cannot decode reference audio: {exc}") from exc
    if audio.size == 0 or sample_rate <= 0:
        raise VoiceProfileError("reference audio contains no samples")
    if not np.isfinite(audio).all():
        raise VoiceProfileError("reference audio contains non-finite samples")
    mono = audio.mean(axis=1)
    peak = float(np.max(np.abs(mono)))
    rms = math.sqrt(float(np.mean(mono.astype(np.float64) ** 2)))
    return AudioMetrics(
        duration_seconds=round(len(mono) / sample_rate, 4),
        sample_rate=int(sample_rate),
        channels=int(audio.shape[1]),
        peak_dbfs=round(20 * math.log10(max(peak, 1e-12)), 2),
        rms_dbfs=round(20 * math.log10(max(rms, 1e-12)), 2),
        clipping_ratio=round(float(np.mean(np.abs(mono) >= 0.999)), 8),
        silence_ratio=round(float(np.mean(np.abs(mono) <= 10 ** (-50 / 20))), 8),
    )


def validate_reference(metrics: AudioMetrics) -> list[str]:
    errors = []
    if metrics.sample_rate != TARGET_SAMPLE_RATE:
        errors.append(f"sample rate must be {TARGET_SAMPLE_RATE} Hz")
    if metrics.channels != 1:
        errors.append("reference must be mono")
    if not MIN_REFERENCE_SECONDS <= metrics.duration_seconds <= MAX_REFERENCE_SECONDS:
        errors.append(
            f"duration must be {MIN_REFERENCE_SECONDS:.0f}-{MAX_REFERENCE_SECONDS:.0f} seconds"
        )
    if metrics.peak_dbfs < -40 or metrics.rms_dbfs < -50:
        errors.append("reference is too quiet")
    if metrics.clipping_ratio > 0.05:
        errors.append("reference is heavily clipped")
    if metrics.silence_ratio > 0.80:
        errors.append("reference contains too much silence")
    return errors


def quality_warnings(metrics: AudioMetrics) -> list[str]:
    warnings = []
    if metrics.duration_seconds > 20:
        warnings.append("long references can carry unwanted prosody; prefer one complete 6-15s sentence")
    if metrics.rms_dbfs < -32:
        warnings.append("reference is quiet; review the clone preview before publishing")
    if metrics.clipping_ratio > 0.001:
        warnings.append("reference contains clipped samples")
    if metrics.silence_ratio > 0.50:
        warnings.append("more than half of the reference is near-silent")
    if metrics.peak_dbfs > -0.1:
        warnings.append("reference peaks are very close to full scale")
    return warnings


def prepare_reference(
    input_path: Path,
    output_path: Path,
    *,
    start_seconds: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> AudioMetrics:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VoiceProfileError("ffmpeg is required to prepare voice references")
    if not input_path.is_file():
        raise VoiceProfileError(f"input audio does not exist: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.", suffix=".wav", dir=str(output_path.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if start_seconds is not None:
            command.extend(["-ss", f"{max(0.0, start_seconds):.3f}"])
        command.extend(["-i", str(input_path)])
        if duration_seconds is not None:
            command.extend(["-t", f"{duration_seconds:.3f}"])
        command.extend([
            "-vn", "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE),
            "-c:a", "pcm_s16le", str(temporary),
        ])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise VoiceProfileError(completed.stderr.strip() or "ffmpeg failed")
        metrics = inspect_reference(temporary)
        errors = validate_reference(metrics)
        if errors:
            raise VoiceProfileError("; ".join(errors))
        os.replace(temporary, output_path)
        return metrics
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_manifest(
    manifest_path: Path,
    *,
    audio_path: Path,
    metrics: AudioMetrics,
    speaker: str,
    transcript: str,
    description: str,
    language: str,
    source_url: str,
    source_title: str,
    rights_basis: str,
    rights_confirmed: bool,
    x_vector_only_mode: bool = False,
) -> Dict[str, Any]:
    transcript = transcript.strip()
    if not x_vector_only_mode and not transcript:
        raise VoiceProfileError("transcript is required unless x-vector-only mode is enabled")
    if not rights_confirmed or not rights_basis.strip():
        raise VoiceProfileError("rights confirmation and rights basis are required")
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "audio": {
            "path": str(audio_path.resolve()),
            "sha256": sha256_file(audio_path),
            "metrics": asdict(metrics),
            "warnings": quality_warnings(metrics),
        },
        "voice": {
            "speaker": speaker.strip(),
            "transcript": transcript,
            "description": description.strip(),
            "language": language.strip() or "Chinese",
            "x_vector_only_mode": bool(x_vector_only_mode),
        },
        "source": {
            "url": source_url.strip(),
            "title": source_title.strip(),
            "rights_basis": rights_basis.strip(),
            "rights_confirmed": True,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(manifest_path, payload)
    return payload


def profile_import_url(endpoint: str) -> str:
    value = endpoint.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VoiceProfileError(f"invalid TTS endpoint: {endpoint}")
    for suffix in ("/voice_profiles/import", "/voice_profiles/design", "/tts_batch", "/tts"):
        if value.endswith(suffix):
            return value[: -len(suffix)] + "/voice_profiles/import"
    return value + "/voice_profiles/import"


def register_profile(
    endpoint: str,
    profile_id: str,
    manifest: Dict[str, Any],
    *,
    force: bool = False,
    timeout: float = 180.0,
) -> Dict[str, Any]:
    audio = manifest.get("audio") or {}
    voice = manifest.get("voice") or {}
    source = manifest.get("source") or {}
    audio_path = Path(str(audio.get("path") or ""))
    if not audio_path.is_file():
        raise VoiceProfileError(f"manifest audio does not exist: {audio_path}")
    current_sha256 = sha256_file(audio_path)
    if current_sha256 != audio.get("sha256"):
        raise VoiceProfileError("reference audio no longer matches its manifest SHA256")
    with audio_path.open("rb") as handle:
        response = requests.post(
            profile_import_url(endpoint),
            files={"audio": (audio_path.name, handle, "audio/wav")},
            data={
                "voice_profile_id": profile_id,
                "sample_text": str(voice.get("transcript") or ""),
                "description": str(voice.get("description") or ""),
                "language": str(voice.get("language") or "Chinese"),
                "x_vector_only_mode": str(bool(voice.get("x_vector_only_mode"))).lower(),
                "source_url": str(source.get("url") or ""),
                "source_title": str(source.get("title") or ""),
                "rights_basis": str(source.get("rights_basis") or ""),
                "rights_confirmed": str(bool(source.get("rights_confirmed"))).lower(),
                "expected_sha256": current_sha256,
                "force": str(bool(force)).lower(),
            },
            timeout=timeout,
        )
    if response.status_code >= 400:
        detail = response.text[:1000].strip()
        raise VoiceProfileError(
            f"profile import failed ({response.status_code})" + (f": {detail}" if detail else "")
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise VoiceProfileError("profile import returned invalid JSON") from exc
    if str(payload.get("voice_profile_id") or "") != profile_id:
        raise VoiceProfileError("profile import returned an unexpected profile ID")
    return payload


def bind_character_profile(
    book_dir: Path,
    character: str,
    profile_id: str,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    state_dir = book_dir / "state"
    characters_path = state_dir / "characters.json"
    aliases_path = state_dir / "aliases.json"
    voices_path = state_dir / "voices.json"
    characters = _read_json_object(characters_path)
    aliases = _read_json_object(aliases_path)
    voices = _read_json_object(voices_path)

    character_id = character if character in characters else None
    if character_id is None:
        character_id = aliases.get(character)
    if character_id is None:
        matches = [
            key for key, record in characters.items()
            if isinstance(record, dict) and str(record.get("name") or "") == character
        ]
        if len(matches) == 1:
            character_id = matches[0]
    if not character_id or character_id not in characters:
        raise VoiceProfileError(f"character not found: {character}")
    character_record = characters[character_id]
    voice_id = str(character_record.get("voice_id") or "")
    if not voice_id or voice_id not in voices or not isinstance(voices[voice_id], dict):
        raise VoiceProfileError(f"character {character_id} has no persistent voice record")

    audio = manifest.get("audio") or {}
    voice = manifest.get("voice") or {}
    source = manifest.get("source") or {}
    audio_path = Path(str(audio.get("path") or "")).resolve()
    project_root = book_dir.resolve().parents[1]
    try:
        reference_value = str(audio_path.relative_to(project_root))
    except ValueError:
        reference_value = str(audio_path)

    record = voices[voice_id]
    previous_profile = str(record.get("voice_profile_id") or "").strip()
    if previous_profile and previous_profile != profile_id:
        record["previous_voice_profile_id"] = previous_profile
    record.update({
        "type": "profile",
        "reference_audio": reference_value,
        "ref_audio": reference_value,
        "ref_text": str(voice.get("transcript") or ""),
        "voice_profile_id": profile_id,
        "voice_profile_backend": "xc",
        "voice_profile_status": "ready",
        "profile_kind": "imported_reference",
        "profile_description": str(voice.get("description") or ""),
        "profile_sample_text": str(voice.get("transcript") or ""),
        "profile_content_sha256": str(audio.get("sha256") or ""),
        "profile_source": source,
        "profile_ready_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "voice_profile_error": None,
        "locked": True,
    })
    _atomic_json_write(voices_path, voices)
    return {
        "character_id": character_id,
        "voice_id": voice_id,
        "voice_profile_id": profile_id,
        "previous_voice_profile_id": previous_profile or None,
    }


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceProfileError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VoiceProfileError(f"expected a JSON object in {path}")
    return value


def _atomic_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
