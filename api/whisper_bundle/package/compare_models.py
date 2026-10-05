"""Compare two saved Faster-Whisper JSON results on one referenced audio sample."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)


def words(text: str) -> list[str]:
    return normalize_text(text).split()


def chars(text: str) -> list[str]:
    return list(re.sub(r"\s+", "", normalize_text(text)))


def reference_text(metadata: dict) -> str:
    if "transcription" in metadata:
        return metadata["transcription"]
    if "transcript_tts" in metadata:
        lines = []
        for line in metadata["transcript_tts"].splitlines():
            _, separator, content = line.partition(":")
            lines.append(content if separator else line)
        return " ".join(lines)
    raise KeyError("Metadata must contain transcription or transcript_tts")


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, ref_item in enumerate(reference, start=1):
        current = [row]
        for column, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[column - 1] + (ref_item != hyp_item),
                    current[column - 1] + 1,
                    previous[column] + 1,
                )
            )
        previous = current
    return previous[-1]


def timestamp_stats(result: dict) -> dict[str, int | float]:
    duration = float(result["duration_seconds"])
    total = valid = invalid = monotonic_errors = 0
    for segment in result.get("segments", []):
        previous_end = float(segment["start"])
        for item in segment.get("words", []):
            total += 1
            start, end = item.get("start"), item.get("end")
            if (
                isinstance(start, (int, float))
                and isinstance(end, (int, float))
                and 0 <= start <= end <= duration + 0.01
            ):
                valid += 1
                if start < previous_end - 0.01:
                    monotonic_errors += 1
                previous_end = end
            else:
                invalid += 1
    return {
        "words": total,
        "valid": valid,
        "invalid": invalid,
        "monotonic_errors": monotonic_errors,
        "coverage_percent": (100 * valid / total) if total else 0.0,
    }


def score(result: dict, reference: str) -> dict:
    reference_words = words(reference)
    hypothesis_words = words(" ".join(s["text"] for s in result["segments"]))
    reference_chars = chars(reference)
    hypothesis_chars = chars(" ".join(s["text"] for s in result["segments"]))
    word_edits = edit_distance(reference_words, hypothesis_words)
    char_edits = edit_distance(reference_chars, hypothesis_chars)
    return {
        "reference_words": len(reference_words),
        "hypothesis_words": len(hypothesis_words),
        "word_edit_distance": word_edits,
        "wer_percent": 100 * word_edits / len(reference_words) if reference_words else 0.0,
        "reference_chars": len(reference_chars),
        "hypothesis_chars": len(hypothesis_chars),
        "char_edit_distance": char_edits,
        "cer_percent": 100 * char_edits / len(reference_chars) if reference_chars else 0.0,
        "timestamps": timestamp_stats(result),
        "model_load_seconds": result.get("model_load_seconds"),
        "inference_seconds": result.get("inference_seconds", result.get("processing_seconds")),
        "real_time_factor": result.get("real_time_factor"),
    }


def fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
    reference = reference_text(metadata)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    baseline_score = score(baseline, reference)
    candidate_score = score(candidate, reference)

    lines = [
        "# BuzzASR vs Whisper large-v3 comparison",
        "",
        f"Reference metadata: `{args.metadata}`",
        "",
        "This is a small local comparison, not a replacement for a benchmark on an independent call-center test set.",
        "The OneVoice sample, when used, is synthetic AI-generated speech.",
        "",
        "| Metric | Whisper large-v3 | BuzzASR |",
        "|---|---:|---:|",
        f"| WER (%) | {fmt(baseline_score['wer_percent'])} | {fmt(candidate_score['wer_percent'])} |",
        f"| CER (%) | {fmt(baseline_score['cer_percent'])} | {fmt(candidate_score['cer_percent'])} |",
        f"| Hypothesis words | {baseline_score['hypothesis_words']} | {candidate_score['hypothesis_words']} |",
        f"| Valid word timestamps | {baseline_score['timestamps']['valid']}/{baseline_score['timestamps']['words']} | {candidate_score['timestamps']['valid']}/{candidate_score['timestamps']['words']} |",
        f"| Invalid timestamps | {baseline_score['timestamps']['invalid']} | {candidate_score['timestamps']['invalid']} |",
        f"| Timestamp monotonicity errors | {baseline_score['timestamps']['monotonic_errors']} | {candidate_score['timestamps']['monotonic_errors']} |",
        f"| Model load (s) | {fmt(baseline_score['model_load_seconds'])} | {fmt(candidate_score['model_load_seconds'])} |",
        f"| Inference (s) | {fmt(baseline_score['inference_seconds'])} | {fmt(candidate_score['inference_seconds'])} |",
        f"| RTF | {fmt(baseline_score['real_time_factor'], 3)} | {fmt(candidate_score['real_time_factor'], 3)} |",
        "",
        "## Interpretation",
        "",
        "- WER/CER are computed locally against the supplied metadata using the same normalization for both models.",
        "- Timestamp checks prove structural validity (range, order, and presence), not boundary accuracy against manually aligned labels.",
        "- Published BuzzASR benchmark values must remain labeled as literature/model-card results; the values above are this project's local measurements.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote", args.output.resolve())
    print(json.dumps({"whisper_large_v3": baseline_score, "buzzasr": candidate_score}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
