"""CLI wrapper around the reusable ASR function."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .asr import MODEL_ALIASES, transcribe_audio
except ImportError:  # Supports direct execution from this package directory.
    from asr import MODEL_ALIASES, transcribe_audio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Input audio path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Directory for JSON, TXT and SRT files",
    )
    parser.add_argument("--model", default="large-v3", choices=tuple(MODEL_ALIASES))
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--language", default="vi")
    parser.add_argument("--beam-size", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.audio.is_file():
        print(f"Input audio does not exist: {args.audio}", file=sys.stderr)
        return 2

    print(
        f"Transcribing model={args.model} device={args.device} "
        f"compute_type={args.compute_type}"
    )
    result = transcribe_audio(
        args.audio,
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        beam_size=args.beam_size,
        output_dir=args.output_dir,
    )

    print(f"Detected language: {result['language_detected']} ({result['language_probability']:.3f})")
    print(f"Audio duration: {result['duration_seconds']:.2f}s")
    print(f"Segments: {len(result['segments'])}")
    print(
        f"Word timestamps: {result['word_timestamp_count']} valid, "
        f"{result['word_without_timestamp_count']} missing/invalid"
    )
    print(f"Model load time: {result['model_load_seconds']:.2f}s")
    print(
        f"Inference time: {result['inference_seconds']:.2f}s; "
        f"total: {result['processing_seconds']:.2f}s "
        f"(RTF {result['real_time_factor']:.3f})"
    )
    if result["files"]:
        print(f"JSON: {result['files']['json']}")
        print(f"TXT:  {result['files']['txt']}")
        print(f"SRT:  {result['files']['srt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
