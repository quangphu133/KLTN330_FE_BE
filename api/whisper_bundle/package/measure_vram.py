"""Run one transcription and record GPU memory sampled during the run."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def gpu_memory_mib() -> int | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
        )
        first = next(csv.reader(completed.stdout.splitlines()), None)
        return int(first[0].strip()) if first else None
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sample-ms", type=int, default=200)
    args = parser.parse_args()

    baseline = gpu_memory_mib()
    samples: list[dict[str, int | float]] = []
    command = [
        sys.executable,
        "transcribe_sample.py",
        str(args.audio),
        "--model",
        args.model,
        "--output-dir",
        str(args.output_dir),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    started = time.perf_counter()
    while process.poll() is None:
        value = gpu_memory_mib()
        if value is not None:
            samples.append({"elapsed_seconds": time.perf_counter() - started, "memory_mib": value})
        time.sleep(max(args.sample_ms, 50) / 1000)
    stdout, _ = process.communicate()
    final_value = gpu_memory_mib()
    if final_value is not None:
        samples.append({"elapsed_seconds": time.perf_counter() - started, "memory_mib": final_value})

    peak = max((item["memory_mib"] for item in samples), default=baseline)
    report = {
        "model": args.model,
        "audio": str(args.audio.resolve()),
        "sampling_interval_ms": args.sample_ms,
        "baseline_memory_mib": baseline,
        "peak_memory_mib": peak,
        "peak_delta_mib": peak - baseline if baseline is not None and peak is not None else None,
        "samples": samples,
        "return_code": process.returncode,
        "transcription_stdout": stdout,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"VRAM report: {args.report.resolve()}")
    print(f"baseline_mib={baseline} peak_mib={peak} delta_mib={report['peak_delta_mib']}")
    print(stdout, end="")
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
