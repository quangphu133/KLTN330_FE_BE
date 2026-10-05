"""Validate the reproducible Faster-Whisper smoke-test output."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    result = json.loads(args.result.read_text(encoding="utf-8"))
    expected = normalize_words(metadata["transcription"])
    actual = normalize_words(" ".join(segment["text"] for segment in result["segments"]))

    if expected != actual:
        print("Transcript mismatch")
        print("expected:", expected)
        print("actual:  ", actual)
        return 1

    duration = float(result["duration_seconds"])
    word_count = 0
    for segment in result["segments"]:
        if not (0 <= segment["start"] <= segment["end"] <= duration + 0.01):
            raise AssertionError(f"Invalid segment range: {segment}")
        previous_end = segment["start"]
        for word in segment["words"]:
            word_count += 1
            start = word["start"]
            end = word["end"]
            if start is None or end is None or not (0 <= start <= end <= duration + 0.01):
                raise AssertionError(f"Invalid word timestamp: {word}")
            if start < previous_end - 0.01:
                raise AssertionError(f"Words are out of order: {word}")
            previous_end = end

    if word_count != len(expected):
        raise AssertionError(f"Expected {len(expected)} words, got {word_count}")
    if result["word_without_timestamp_count"] != 0:
        raise AssertionError("Some words do not have valid timestamps")

    print(f"PASS: transcript words match ({word_count})")
    print("PASS: every word has a monotonic in-range timestamp")
    print(f"PASS: device={result['device']} compute_type={result['compute_type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
