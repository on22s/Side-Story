import base64
import hashlib
import io
import json
import math
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from qwen_tts import Qwen3TTSModel


ROOT = Path(os.environ.get("QWEN3_TTS_ROOT", Path(__file__).resolve().parent))
DEFAULT_MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_DESIGN_MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_BASE_MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-Base"
MODEL_PATH = os.environ.get("QWEN3_TTS_MODEL", str(DEFAULT_MODEL))
DESIGN_MODEL_PATH = os.environ.get("QWEN3_TTS_DESIGN_MODEL", str(DEFAULT_DESIGN_MODEL))
BASE_MODEL_PATH = os.environ.get("QWEN3_TTS_BASE_MODEL", str(DEFAULT_BASE_MODEL))
PROFILE_ROOT = Path(os.environ.get("QWEN3_TTS_PROFILE_ROOT", str(ROOT / "voice_profiles")))
PROFILE_INDEX = PROFILE_ROOT / "profiles.json"
DEVICE_MAP = os.environ.get("QWEN3_TTS_DEVICE", "cuda:0")
REQUESTED_ATTN = os.environ.get("QWEN3_TTS_ATTN", "flash_attention_2")
BATCH_MAX_ITEMS = max(1, int(os.environ.get("QWEN3_TTS_BATCH_MAX_ITEMS", "48")))
PROFILE_IMPORT_MAX_BYTES = max(
    1, int(os.environ.get("QWEN3_TTS_PROFILE_IMPORT_MAX_BYTES", str(32 * 1024 * 1024)))
)
PROFILE_IMPORT_MIN_SECONDS = max(
    0.1, float(os.environ.get("QWEN3_TTS_PROFILE_IMPORT_MIN_SECONDS", "3"))
)
PROFILE_IMPORT_MAX_SECONDS = max(
    PROFILE_IMPORT_MIN_SECONDS,
    float(os.environ.get("QWEN3_TTS_PROFILE_IMPORT_MAX_SECONDS", "30")),
)
PROFILE_SAMPLE_RATE = 24000

app = FastAPI(title="Qwen3-TTS 1.7B on PPU", version="0.2.0")
generation_lock = threading.Lock()
model: Optional[Qwen3TTSModel] = None
model_kind: Optional[str] = None
resolved_attn: Optional[str] = None
load_error: Optional[str] = None
clone_prompt_cache: Dict[str, object] = {}


def _load_model(path: str, kind: str):
    global model, model_kind, resolved_attn, load_error
    model_kwargs = {
        "device_map": DEVICE_MAP,
        "dtype": torch.bfloat16,
        "attn_implementation": REQUESTED_ATTN,
    }
    try:
        print(f"loading {kind} model from {path}", flush=True)
        model = Qwen3TTSModel.from_pretrained(path, **model_kwargs)
        model_kind = kind
        resolved_attn = REQUESTED_ATTN
        load_error = None
        print(f"{kind} model loaded with attention={resolved_attn}", flush=True)
    except Exception as first_error:
        if REQUESTED_ATTN == "eager" or os.environ.get("QWEN3_TTS_NO_FALLBACK") == "1":
            load_error = f"{type(first_error).__name__}: {first_error}"
            raise
        print(
            f"flash_attention_2 load failed ({type(first_error).__name__}: {first_error}); "
            "retrying with eager",
            flush=True,
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        model_kwargs["attn_implementation"] = "eager"
        try:
            model = Qwen3TTSModel.from_pretrained(path, **model_kwargs)
            model_kind = kind
            resolved_attn = "eager"
            load_error = None
            print(f"{kind} model loaded with attention=eager", flush=True)
        except Exception as second_error:
            load_error = f"{type(second_error).__name__}: {second_error}"
            raise


def _model_path(kind: str) -> str:
    return {
        "custom": MODEL_PATH,
        "design": DESIGN_MODEL_PATH,
        "base": BASE_MODEL_PATH,
    }[kind]


def _ensure_model(kind: str):
    global model, model_kind, load_error
    if model is not None and model_kind == kind:
        return model
    if model is not None:
        print(f"unloading {model_kind or 'current'} model before loading {kind}", flush=True)
        model = None
        model_kind = None
        clone_prompt_cache.clear()
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    try:
        _load_model(_model_path(kind), kind)
    except Exception as exc:
        load_error = f"{type(exc).__name__}: {exc}"
        raise HTTPException(
            status_code=503,
            detail=f"{kind} model is not available: {load_error}",
        ) from exc
    return model


def load_model():
    _load_model(MODEL_PATH, "custom")


try:
    load_model()
except Exception as exc:
    load_error = f"{type(exc).__name__}: {exc}"
    print(f"model load failed: {load_error}", flush=True)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    speaker: str = "Dylan"
    voice_profile_id: Optional[str] = None
    instruct: str = ""
    language: str = "Chinese"


class TTSBatchRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1, max_length=BATCH_MAX_ITEMS)
    speaker: Union[str, List[str]] = "Dylan"
    voice_profile_id: Optional[Union[str, List[Optional[str]]]] = None
    voice_profile_ids: Optional[List[Optional[str]]] = None
    instruct: Union[str, List[str]] = ""
    language: Union[str, List[str]] = "Chinese"


class VoiceProfileDesignRequest(BaseModel):
    voice_profile_id: str = Field(..., min_length=1, max_length=160)
    description: str = Field(..., min_length=1, max_length=1200)
    sample_text: str = Field(..., min_length=1, max_length=500)
    language: str = "Chinese"
    seed: int = -1
    force: bool = False


def _wav_bytes(audio, sample_rate):
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _clean_batch_texts(texts):
    cleaned = [str(text).strip() for text in texts]
    if any(not text for text in cleaned):
        raise HTTPException(status_code=422, detail="texts must not contain empty items")
    if any(len(text) > 2000 for text in cleaned):
        raise HTTPException(status_code=422, detail="each text must be at most 2000 characters")
    return cleaned


def _as_batch(value, size, default):
    if isinstance(value, list):
        if len(value) != size:
            raise HTTPException(status_code=422, detail="batch fields must match texts length")
        return list(value)
    return [default if value is None else value for _ in range(size)]


def _profile_id(value: Optional[str]) -> Optional[str]:
    value = str(value or "").strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value):
        raise HTTPException(status_code=422, detail="invalid voice_profile_id")
    return value


def _load_profiles() -> Dict[str, dict]:
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    if not PROFILE_INDEX.exists():
        return {}
    try:
        value = json.loads(PROFILE_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"cannot read voice profiles: {exc}") from exc
    return value if isinstance(value, dict) else {}


def _save_profiles(profiles: Dict[str, dict]) -> None:
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".profiles.", suffix=".tmp", dir=str(PROFILE_ROOT))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profiles, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, PROFILE_INDEX)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _profile_audio_path(profile_id: str) -> Path:
    return PROFILE_ROOT / f"{profile_id}.wav"


def _normalise_profile_audio(payload: bytes):
    """Decode an uploaded clip and return canonical 24 kHz mono PCM data."""
    if not payload:
        raise HTTPException(status_code=422, detail="reference audio is empty")
    if len(payload) > PROFILE_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"reference audio exceeds {PROFILE_IMPORT_MAX_BYTES} bytes",
        )
    try:
        audio, source_rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"cannot decode reference audio: {exc}") from exc
    if audio.size == 0 or source_rate <= 0:
        raise HTTPException(status_code=422, detail="reference audio contains no samples")
    if not torch.isfinite(torch.from_numpy(audio)).all():
        raise HTTPException(status_code=422, detail="reference audio contains non-finite samples")

    source_channels = int(audio.shape[1])
    mono = audio.mean(axis=1)
    if source_rate != PROFILE_SAMPLE_RATE:
        try:
            import librosa
            mono = librosa.resample(
                mono,
                orig_sr=source_rate,
                target_sr=PROFILE_SAMPLE_RATE,
                res_type="soxr_hq",
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"cannot resample reference audio: {exc}") from exc

    duration = len(mono) / PROFILE_SAMPLE_RATE
    if duration < PROFILE_IMPORT_MIN_SECONDS or duration > PROFILE_IMPORT_MAX_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"reference duration {duration:.2f}s is outside "
                f"{PROFILE_IMPORT_MIN_SECONDS:.2f}-{PROFILE_IMPORT_MAX_SECONDS:.2f}s"
            ),
        )
    peak = float(abs(mono).max())
    rms = math.sqrt(float((mono.astype("float64") ** 2).mean()))
    clipping_ratio = float((abs(mono) >= 0.999).mean())
    silence_ratio = float((abs(mono) <= 10 ** (-50 / 20)).mean())
    if peak < 0.01 or rms < 0.003:
        raise HTTPException(status_code=422, detail="reference audio is too quiet")
    if clipping_ratio > 0.05:
        raise HTTPException(status_code=422, detail="reference audio is heavily clipped")
    if silence_ratio > 0.80:
        raise HTTPException(status_code=422, detail="reference audio contains too much silence")

    output = io.BytesIO()
    sf.write(output, mono, PROFILE_SAMPLE_RATE, format="WAV", subtype="PCM_16")
    canonical = output.getvalue()
    metrics = {
        "duration_seconds": round(duration, 4),
        "sample_rate": PROFILE_SAMPLE_RATE,
        "channels": 1,
        "source_sample_rate": int(source_rate),
        "source_channels": source_channels,
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-12)), 2),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "clipping_ratio": round(clipping_ratio, 8),
        "silence_ratio": round(silence_ratio, 8),
    }
    return canonical, metrics


def _require_profile(profile_id: str) -> dict:
    profile_id = _profile_id(profile_id) or ""
    profiles = _load_profiles()
    record = profiles.get(profile_id)
    audio_path = _profile_audio_path(profile_id)
    if not isinstance(record, dict) or not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"voice profile not found: {profile_id}")
    record["reference_audio"] = str(audio_path)
    return record


def _profile_prompt(profile_id: str):
    if profile_id in clone_prompt_cache:
        return clone_prompt_cache[profile_id]
    record = _require_profile(profile_id)
    clone_model = _ensure_model("base")
    ref_text = record.get("sample_text") or None
    x_vector_only_mode = bool(record.get("x_vector_only_mode", False))
    prompt = clone_model.create_voice_clone_prompt(
        ref_audio=record["reference_audio"],
        ref_text=ref_text,
        x_vector_only_mode=x_vector_only_mode,
    )
    clone_prompt_cache[profile_id] = prompt
    return prompt


def _generate_custom(texts, speakers, instructs, languages):
    custom_model = _ensure_model("custom")
    return custom_model.generate_custom_voice(
        text=texts,
        language=languages,
        speaker=speakers,
        instruct=instructs,
        non_streaming_mode=True,
    )


def _generate_profiles(texts, profile_ids, languages):
    grouped = {}
    for index, profile_id in enumerate(profile_ids):
        grouped.setdefault(profile_id, []).append(index)
    output = [None] * len(texts)
    sample_rate = None
    clone_model = _ensure_model("base")
    for profile_id, indices in grouped.items():
        prompt = _profile_prompt(profile_id)
        batch_texts = [texts[index] for index in indices]
        batch_languages = [languages[index] for index in indices]
        wavs, current_rate = clone_model.generate_voice_clone(
            text=batch_texts,
            language=batch_languages,
            voice_clone_prompt=prompt,
        )
        if wavs is None or len(wavs) != len(indices):
            raise RuntimeError(
                f"profile batch {profile_id} returned {0 if wavs is None else len(wavs)} "
                f"items for {len(indices)} texts"
            )
        sample_rate = current_rate
        for index, audio in zip(indices, wavs):
            output[index] = audio
    return output, sample_rate


@app.get("/health")
def health():
    profiles = _load_profiles()
    payload = {
        "status": "ok" if model is not None else "degraded",
        "model": MODEL_PATH,
        "loaded_model": model_kind,
        "design_model": DESIGN_MODEL_PATH,
        "base_model": BASE_MODEL_PATH,
        "device": DEVICE_MAP,
        "attention": resolved_attn,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "ppu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "batch_endpoint": "/tts_batch",
        "batch_max_items": BATCH_MAX_ITEMS,
        "voice_profile_endpoint": "/voice_profiles/design",
        "voice_profile_import_endpoint": "/voice_profiles/import",
        "voice_profile_tts": True,
        "voice_profiles": len(profiles),
    }
    if model is None:
        return JSONResponse(status_code=503, content={**payload, "error": load_error})
    return payload


def _model_available(path: str) -> bool:
    model_dir = Path(path)
    return model_dir.exists() and any(model_dir.glob("*.safetensors"))


@app.get("/capabilities")
def capabilities():
    design_available = _model_available(DESIGN_MODEL_PATH)
    base_available = _model_available(BASE_MODEL_PATH)
    return {
        "protocol_version": 2,
        "batch_max_items": BATCH_MAX_ITEMS,
        "max_text_chars": 2000,
        "custom_voice": _model_available(MODEL_PATH),
        "voice_design": design_available,
        "voice_profiles": design_available and base_available,
        "profile_endpoint": "/voice_profiles/design",
        "profile_import_endpoint": "/voice_profiles/import",
        "profile_field": "voice_profile_id",
        "models": {
            "custom": _model_available(MODEL_PATH),
            "design": design_available,
            "base": base_available,
        },
    }


@app.get("/voice_profiles")
def voice_profiles():
    profiles = _load_profiles()
    return {
        "profiles": [
            {"voice_profile_id": profile_id, **dict(record)}
            for profile_id, record in sorted(profiles.items())
            if isinstance(record, dict)
        ]
    }


@app.post("/voice_profiles/import")
async def import_voice_profile(
    audio: UploadFile = File(...),
    voice_profile_id: str = Form(...),
    sample_text: str = Form(""),
    description: str = Form(""),
    language: str = Form("Chinese"),
    x_vector_only_mode: bool = Form(False),
    source_url: str = Form(""),
    source_title: str = Form(""),
    rights_basis: str = Form(""),
    rights_confirmed: bool = Form(False),
    expected_sha256: str = Form(""),
    force: bool = Form(False),
):
    """Import an authorised real reference clip as an immutable voice profile."""
    profile_id = _profile_id(voice_profile_id)
    if not profile_id:
        raise HTTPException(status_code=422, detail="voice_profile_id is required")
    transcript = sample_text.strip()
    if not x_vector_only_mode and not transcript:
        raise HTTPException(
            status_code=422,
            detail="sample_text is required unless x_vector_only_mode is enabled",
        )
    if len(transcript) > 1000:
        raise HTTPException(status_code=422, detail="sample_text must be at most 1000 characters")
    if not rights_confirmed or not rights_basis.strip():
        raise HTTPException(
            status_code=422,
            detail="rights_confirmed and rights_basis are required for imported voices",
        )

    payload = await audio.read(PROFILE_IMPORT_MAX_BYTES + 1)
    upload_sha256 = hashlib.sha256(payload).hexdigest()
    expected = expected_sha256.strip().lower()
    if expected and expected != upload_sha256:
        raise HTTPException(status_code=422, detail="uploaded audio SHA256 does not match manifest")
    canonical, metrics = _normalise_profile_audio(payload)
    content_sha256 = hashlib.sha256(canonical).hexdigest()
    audio_path = _profile_audio_path(profile_id)

    with generation_lock:
        profiles = _load_profiles()
        existing = profiles.get(profile_id)
        if isinstance(existing, dict) and audio_path.exists() and not force:
            if existing.get("content_sha256") == content_sha256:
                return {
                    "voice_profile_id": profile_id,
                    "status": "ready",
                    "cached": True,
                    "content_sha256": content_sha256,
                    "metrics": existing.get("metrics") or metrics,
                }
            raise HTTPException(
                status_code=409,
                detail="voice profile already exists with different audio; use a new versioned ID",
            )

        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{profile_id}.", suffix=".wav.tmp", dir=str(PROFILE_ROOT)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, audio_path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

        now = time.time()
        profiles[profile_id] = {
            "profile_kind": "imported_reference",
            "description": description.strip(),
            "sample_text": transcript,
            "language": language.strip() or "Chinese",
            "sample_rate": PROFILE_SAMPLE_RATE,
            "reference_audio": str(audio_path),
            "x_vector_only_mode": bool(x_vector_only_mode),
            "content_sha256": content_sha256,
            "upload_sha256": upload_sha256,
            "metrics": metrics,
            "source": {
                "url": source_url.strip(),
                "title": source_title.strip(),
                "rights_basis": rights_basis.strip(),
                "rights_confirmed": True,
            },
            "created_at": (existing or {}).get("created_at", now),
            "updated_at": now,
        }
        _save_profiles(profiles)
        clone_prompt_cache.pop(profile_id, None)

    return {
        "voice_profile_id": profile_id,
        "status": "ready",
        "cached": False,
        "content_sha256": content_sha256,
        "metrics": metrics,
    }


@app.post("/voice_profiles/design")
def design_voice_profile(req: VoiceProfileDesignRequest):
    profile_id = _profile_id(req.voice_profile_id)
    if not profile_id:
        raise HTTPException(status_code=422, detail="voice_profile_id is required")
    profiles = _load_profiles()
    audio_path = _profile_audio_path(profile_id)
    existing = profiles.get(profile_id)
    if not req.force and isinstance(existing, dict) and audio_path.exists():
        return {
            "voice_profile_id": profile_id,
            "status": "ready",
            "cached": True,
            "reference_audio": str(audio_path),
        }
    try:
        with generation_lock:
            design_model = _ensure_model("design")
            if req.seed >= 0:
                torch.manual_seed(req.seed)
            wavs, sample_rate = design_model.generate_voice_design(
                text=req.sample_text.strip(),
                language=req.language,
                instruct=req.description.strip(),
                non_streaming_mode=True,
                max_new_tokens=2048,
            )
            if wavs is None or len(wavs) == 0:
                raise RuntimeError("VoiceDesign returned no audio")
            PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
            temporary = audio_path.with_name(f".{audio_path.name}.{os.getpid()}.tmp")
            sf.write(str(temporary), wavs[0], sample_rate, format="WAV", subtype="PCM_16")
            os.replace(temporary, audio_path)
            profiles[profile_id] = {
                "description": req.description.strip(),
                "sample_text": req.sample_text.strip(),
                "language": req.language,
                "sample_rate": sample_rate,
                "reference_audio": str(audio_path),
                "created_at": (existing or {}).get("created_at", time.time()),
                "updated_at": time.time(),
            }
            _save_profiles(profiles)
            clone_prompt_cache.pop(profile_id, None)
        return {
            "voice_profile_id": profile_id,
            "status": "ready",
            "cached": False,
            "reference_audio": str(audio_path),
        }
    except HTTPException:
        raise
    except Exception as exc:
        try:
            audio_path.unlink()
        except FileNotFoundError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"VoiceDesign failed: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/tts")
def tts(req: TTSRequest):
    try:
        with generation_lock:
            if req.voice_profile_id:
                wavs, sample_rate = _generate_profiles(
                    [req.text.strip()], [_profile_id(req.voice_profile_id)], [req.language]
                )
            else:
                wavs, sample_rate = _generate_custom(
                    [req.text.strip()],
                    [req.speaker],
                    [req.instruct.strip() or None],
                    [req.language],
                )
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        return Response(content=_wav_bytes(wavs[0], sample_rate), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/tts_batch")
def tts_batch(req: TTSBatchRequest):
    texts = _clean_batch_texts(req.texts)
    size = len(texts)
    speakers = _as_batch(req.speaker, size, "Dylan")
    instructs = _as_batch(req.instruct, size, "")
    languages = _as_batch(req.language, size, "Chinese")
    raw_profiles = req.voice_profile_ids if req.voice_profile_ids is not None else req.voice_profile_id
    profile_ids = [_profile_id(value) for value in _as_batch(raw_profiles, size, None)]
    try:
        with generation_lock:
            wavs = [None] * size
            sample_rate = None
            profile_indices = [index for index, profile_id in enumerate(profile_ids) if profile_id]
            custom_indices = [index for index, profile_id in enumerate(profile_ids) if not profile_id]
            if profile_indices:
                profile_wavs, sample_rate = _generate_profiles(
                    [texts[index] for index in profile_indices],
                    [profile_ids[index] for index in profile_indices],
                    [languages[index] for index in profile_indices],
                )
                for index, audio in zip(profile_indices, profile_wavs):
                    wavs[index] = audio
            if custom_indices:
                custom_wavs, custom_rate = _generate_custom(
                    [texts[index] for index in custom_indices],
                    [speakers[index] for index in custom_indices],
                    [instructs[index] or None for index in custom_indices],
                    [languages[index] for index in custom_indices],
                )
                if sample_rate is None:
                    sample_rate = custom_rate
                for index, audio in zip(custom_indices, custom_wavs):
                    wavs[index] = audio
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        if sample_rate is None or any(audio is None for audio in wavs):
            raise RuntimeError(f"batch returned incomplete audio for {size} texts")
        audios = [
            base64.b64encode(_wav_bytes(audio, sample_rate)).decode("ascii")
            for audio in wavs
        ]
        return {
            "count": len(audios),
            "sample_rate": sample_rate,
            "audios": audios,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
