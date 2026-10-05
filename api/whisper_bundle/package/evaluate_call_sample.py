"""Compare one OneVoice call transcription with its spoken reference text."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def normalize_words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return text.split()


def reference_without_roles(transcript: str) -> list[str]:
    lines = []
    for line in transcript.splitlines():
        _, separator, text = line.partition(":")
        lines.append(text if separator else line)
    return normalize_words(" ".join(lines))


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, reference_word in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_word in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (reference_word != hypothesis_word)
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
    result = json.loads(args.result.read_text(encoding="utf-8"))
    reference = reference_without_roles(metadata["transcript_tts"])
    hypothesis = normalize_words(" ".join(segment["text"] for segment in result["segments"]))
    distance = edit_distance(reference, hypothesis)
    wer = distance / len(reference) if reference else 0.0

    print(f"reference_words={len(reference)}")
    print(f"hypothesis_words={len(hypothesis)}")
    print(f"word_edit_distance={distance}")
    print(f"WER={wer:.2%}")
    print(f"valid_word_timestamps={result['word_timestamp_count']}")
    print(f"missing_word_timestamps={result['word_without_timestamp_count']}")
    print(f"processing_seconds={result['processing_seconds']:.2f}")
    print(f"real_time_factor={result['real_time_factor']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
