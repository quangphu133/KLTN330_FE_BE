"""Reusable local Vietnamese ASR service backed by Faster-Whisper."""

from __future__ import annotations

import gc
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import av
import numpy as np
from faster_whisper import WhisperModel


PACKAGE_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = BUNDLE_ROOT.parent
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "large-v3"
LARGE_V3_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478"
MODEL_ALIASES = {
    "large-v3": {
        "path": str(DEFAULT_MODEL_DIR),
        "source_revision": f"Systran/faster-whisper-large-v3@{LARGE_V3_REVISION}",
    },
}


_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: WhisperModel | None = None
_MODEL_CACHE_KEY: tuple[str, str, str, str] | None = None


def resolve_model(model_name: str) -> tuple[str, str, str | None]:
    """Resolve the single supported model and its pinned local checkpoint."""

    if model_name != "large-v3":
        raise ValueError("Only the large-v3 model is supported")
    alias = MODEL_ALIASES[model_name]
    configured_path = os.environ.get("ASR_MODEL_DIR")
    model_path = Path(configured_path).expanduser() if configured_path else Path(alias["path"])
    if configured_path and not model_path.is_absolute():
        raise ValueError("ASR_MODEL_DIR must be an absolute path")
    if not model_path.is_dir():
        raise FileNotFoundError(
            f"Whisper large-v3 checkpoint is missing: {model_path}. "
            "Download the pinned checkpoint as described in README.md."
        )
    return model_name, str(model_path.resolve()), alias["source_revision"]


def _decode_audio(audio_path: Path) -> tuple[np.ndarray, int, float]:
    """Decode one or two channels to planar float32 at 16 kHz."""

    with av.open(str(audio_path)) as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise ValueError("Audio file has no audio stream")
        original_channels = int(stream.codec_context.channels or 0)
        original_rate = int(stream.codec_context.sample_rate or 0)
        if original_channels not in {1, 2}:
            raise ValueError("Audio must contain one or two channels")
        if original_rate <= 0:
            raise ValueError("Audio sample rate is invalid")
        duration = (
            float(container.duration / av.time_base)
            if container.duration is not None
            else 0.0
        )
        layout = "mono" if original_channels == 1 else "stereo"
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=16000)
        channel_chunks: list[list[np.ndarray]] = [[] for _ in range(original_channels)]
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                for channel in range(original_channels):
                    samples = np.frombuffer(
                        resampled.planes[channel], dtype=np.float32, count=resampled.samples
                    ).copy()
                    channel_chunks[channel].append(samples)
        for resampled in resampler.resample(None):
            for channel in range(original_channels):
                samples = np.frombuffer(
                    resampled.planes[channel], dtype=np.float32, count=resampled.samples
                ).copy()
                channel_chunks[channel].append(samples)

    channel_data = [
        np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
        for chunks in channel_chunks
    ]
    if not any(samples.size for samples in channel_data):
        raise ValueError("Audio contains no decodable samples")
    decoded_duration = max((samples.size for samples in channel_data), default=0) / 16000
    if duration <= 0:
        duration = decoded_duration
    return np.stack(channel_data), original_rate, duration


def _channel_quality(audio: np.ndarray, transcripts: list[str]) -> dict[str, Any]:
    """Flag silence, near-constant channels, and near-duplicate stereo."""

    reasons: list[str] = []
    near_constant = []
    for channel, samples in enumerate(audio):
        is_near_constant = samples.size == 0 or float(np.std(samples)) < 1e-5
        near_constant.append(is_near_constant)
        if is_near_constant:
            reasons.append(f"channel_{channel}_silent_or_near_constant")

    correlation: float | None = None
    if audio.shape[0] == 1:
        reasons.append("mono_audio")
    else:
        left = audio[0].astype(np.float64)
        right = audio[1].astype(np.float64)
        common_length = min(left.size, right.size)
        left = left[:common_length] - np.mean(left[:common_length]) if common_length else left
        right = right[:common_length] - np.mean(right[:common_length]) if common_length else right
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator > 0:
            correlation = float(np.dot(left, right) / denominator)
            if abs(correlation) >= 0.995:
                reasons.append("channels_near_duplicate")
        for channel, transcript in enumerate(transcripts):
            if not transcript.strip():
                reasons.append(f"channel_{channel}_transcript_empty")

    return {
        "auto_role_eligible": audio.shape[0] == 2 and not reasons,
        "reasons": reasons,
        "correlation": correlation,
    }


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    numeric_value = float(value)
    return numeric_value if math.isfinite(numeric_value) else None


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds_part = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{milliseconds_part:03d}"


def _release_cached_model() -> None:
    global _MODEL_CACHE, _MODEL_CACHE_KEY
    if _MODEL_CACHE is not None:
        del _MODEL_CACHE
        _MODEL_CACHE = None
        _MODEL_CACHE_KEY = None
        gc.collect()


def _load_model(
    model_alias: str,
    model_path: str,
    device: str,
    compute_type: str,
) -> tuple[WhisperModel, float]:
    global _MODEL_CACHE, _MODEL_CACHE_KEY
    cache_key = (model_alias, model_path, device, compute_type)
    if _MODEL_CACHE is not None and _MODEL_CACHE_KEY == cache_key:
        return _MODEL_CACHE, 0.0

    _release_cached_model()
    started = time.perf_counter()
    loaded_model = WhisperModel(
        model_path,
        device=device,
        compute_type=compute_type,
    )
    _MODEL_CACHE = loaded_model
    _MODEL_CACHE_KEY = cache_key
    return loaded_model, time.perf_counter() - started


def warm_up_model(
    *,
    model: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> float:
    """Load and cache a model without transcribing an audio file."""

    if device not in {"cuda", "cpu"}:
        raise ValueError("device must be 'cuda' or 'cpu'")
    if not compute_type:
        raise ValueError("compute_type must not be empty")
    model_alias, model_path, _ = resolve_model(model)
    with _MODEL_LOCK:
        _, load_seconds = _load_model(model_alias, model_path, device, compute_type)
    return load_seconds


def _write_outputs(result: dict[str, Any], output_dir: Path, stem: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = (output_dir / f"{stem}.json").resolve()
    txt_path = (output_dir / f"{stem}.txt").resolve()
    srt_path = (output_dir / f"{stem}.srt").resolve()

    txt_lines = [
        f"[{_timestamp(segment['start']).replace(',', '.')} -> "
        f"{_timestamp(segment['end']).replace(',', '.')}] {segment['text']}"
        for segment in result["segments"]
    ]
    srt_blocks = [
        f"{index}\n{_timestamp(segment['start'])} --> "
        f"{_timestamp(segment['end'])}\n{segment['text']}"
        for index, segment in enumerate(result["segments"], start=1)
    ]
    files = {
        "json": str(json_path),
        "txt": str(txt_path),
        "srt": str(srt_path),
    }
    result["files"] = files
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")
    srt_path.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")
    return files


def transcribe_audio(
    audio_path: str | Path,
    *,
    model: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str = "vi",
    beam_size: int = 5,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Transcribe one local audio file and return text plus word timestamps.

    The model is cached per process and configuration. Model loading and
    inference are serialized so multiple Back-end calls cannot overlap on the
    same GPU model. Waiting for the lock and writing optional files are not
    included in ``processing_seconds``.
    """

    if device not in {"cuda", "cpu"}:
        raise ValueError("device must be 'cuda' or 'cpu'")
    if not compute_type:
        raise ValueError("compute_type must not be empty")
    if not language:
        raise ValueError("language must not be empty")
    if not isinstance(beam_size, int) or beam_size < 1:
        raise ValueError("beam_size must be a positive integer")

    audio = Path(audio_path)
    if not audio.is_file():
        raise FileNotFoundError(f"Input audio does not exist: {audio}")

    model_alias, model_path, source_revision = resolve_model(model)
    audio_channels, original_sample_rate, duration = _decode_audio(audio)
    with _MODEL_LOCK:
        loaded_model, model_load_seconds = _load_model(
            model_alias,
            model_path,
            device,
            compute_type,
        )
        transcription_started = time.perf_counter()
        channel_segments: list[tuple[int, dict[str, Any]]] = []
        channel_texts: list[str] = []
        words_with_timestamps = 0
        words_without_timestamps = 0
        first_info = None
        for channel_index, channel_samples in enumerate(audio_channels):
            segments_iter, info = loaded_model.transcribe(
                channel_samples,
                language=language,
                task="transcribe",
                beam_size=beam_size,
                temperature=0.0,
                condition_on_previous_text=False,
                word_timestamps=True,
                vad_filter=False,
            )
            if first_info is None:
                first_info = info
            channel_text = []
            for segment in segments_iter:
                segment_text = segment.text.strip()
                channel_text.append(segment_text)
                words = []
                for word in segment.words or []:
                    start = _finite_or_none(word.start)
                    end = _finite_or_none(word.end)
                    if start is not None and end is not None and end >= start:
                        words_with_timestamps += 1
                    else:
                        words_without_timestamps += 1
                    words.append(
                        {
                            "word": word.word,
                            "start": start,
                            "end": end,
                            "probability": _finite_or_none(word.probability),
                        }
                    )
                channel_segments.append(
                    (
                        channel_index,
                        {
                            "start": float(segment.start),
                            "end": float(segment.end),
                            "text": segment_text,
                            "avg_logprob": _finite_or_none(segment.avg_logprob),
                            "no_speech_prob": _finite_or_none(segment.no_speech_prob),
                            "words": words,
                        },
                    )
                )
            channel_texts.append(" ".join(channel_text))
        inference_seconds = time.perf_counter() - transcription_started

    channel_segments.sort(key=lambda item: (item[1]["start"], item[0], item[1]["end"]))
    segments: list[dict[str, Any]] = []
    next_word_id = 0
    for segment_id, (channel_index, segment) in enumerate(channel_segments):
        segment["id"] = segment_id
        segment["channel"] = channel_index
        for word in segment["words"]:
            word["id"] = next_word_id
            next_word_id += 1
        segments.append(segment)

    channel_quality = _channel_quality(audio_channels, channel_texts)
    result: dict[str, Any] = {
        "source": str(audio.resolve()),
        "model": model_alias,
        "model_path": model_path,
        "model_source_revision": source_revision,
        "model_metadata": {
            "repository": "Systran/faster-whisper-large-v3",
            "revision": LARGE_V3_REVISION,
        },
        "device": device,
        "compute_type": compute_type,
        "language_requested": language,
        "language_detected": first_info.language,
        "language_probability": _finite_or_none(first_info.language_probability),
        "duration_seconds": duration,
        "duration_after_vad_seconds": duration,
        "model_load_seconds": model_load_seconds,
        "inference_seconds": inference_seconds,
        "processing_seconds": model_load_seconds + inference_seconds,
        "real_time_factor": inference_seconds / duration if duration > 0 else None,
        "word_timestamp_count": words_with_timestamps,
        "word_without_timestamp_count": words_without_timestamps,
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "audio_metadata": {
            "num_channels": int(audio_channels.shape[0]),
            "sample_rate": original_sample_rate,
            "duration_seconds": duration,
        },
        "channel_quality": channel_quality,
        "files": None,
    }
    result["diarization"] = {
        "status": "disabled",
        "model": None,
        "device": device,
        "processing_seconds": 0.0,
        "speaker_count": 0,
        "speakers": [],
        "turns": [],
        "utterances": [],
        "role_mapping": {
            "status": "needs_confirmation",
            "suggested_agent_speaker_id": None,
            "suggestion_reason": None,
        },
        "segments": [],
    }

    if output_dir is not None:
        result["files"] = _write_outputs(result, Path(output_dir), audio.stem)

    return result


def _reset_model_cache_for_tests() -> None:
    """Release the process cache; intended for tests and controlled shutdown."""

    with _MODEL_LOCK:
        _release_cached_model()
