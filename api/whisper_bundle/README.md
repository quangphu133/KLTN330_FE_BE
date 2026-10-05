# Whisper large-v3 deployment bundle

This bundle contains the Faster-Whisper service code, authenticated job API,
Python client, tests, and documentation. It supports one model only:
`Systran/faster-whisper-large-v3` at revision
`edaa852ec7e145841d8ffdb056a99866b5f0a478`.

## Checkpoint

The checkpoint is not included in the source distribution. From the project
root, download the public model with the standard Hugging Face client:

```powershell
hf download Systran/faster-whisper-large-v3 `
  --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 `
  --local-dir models\large-v3
```

The checkpoint occupies about 3.09 GB. A token is not required. If it is
stored elsewhere, set `ASR_MODEL_DIR` to the absolute checkpoint directory.
Do not delete existing model folders while migrating a deployment.

## Audio and result behavior

The service decodes mono and stereo audio with PyAV, keeps the full timeline,
resamples each channel independently to 16 kHz, and calls the same cached
large-v3 model sequentially with `vad_filter=False`. Stereo results are sorted
by segment start time and channel. Segment and word IDs are stable integers
within a result.

The response retains the established text, segment, duration, timing, and
diarization fields. It adds `audio_metadata` and `channel_quality`; the
`auto_role_eligible` flag checks signal quality and transcript availability.
It cannot establish speaker identity, role, or proof that two microphone
channels are independent. Role assignment belongs to the backend workflow.

## Local use

```python
from whisper_bundle.package.asr import transcribe_audio

result = transcribe_audio("samples/fleurs_vi_test.wav")
print(result["text"])
```

Optional `output_dir` writes JSON, TXT, and SRT files. The CLI defaults to
large-v3 and also accepts only that model.

## API and client

The GPU service provides Bearer-authenticated `GET /health`, `POST /jobs`,
`GET /jobs/{job_id}`, and `GET /jobs/{job_id}/result`, `/txt`, and `/srt`.
The API response strips the machine's model path. See
[README_API.md](README_API.md) for server setup and
[package/README_BACKEND.md](package/README_BACKEND.md) for direct Python use.

The remote Python client requires `requests` only. Copy
`whisper_bundle/client` to the backend as `buzzasr_client` and use
`submit_audio()` followed by `wait_for_result()`.
