# Local Python integration

For normal deployment, the backend calls the authenticated HTTP API; it does
not import this module. The standalone API command is in
[`../README_API.md`](../README_API.md). To call the local transcription
function for a script or QA task, start in the repository root and change to
`api/` so `whisper_bundle` is on the import path:

```powershell
Set-Location .\api
```

```python
from whisper_bundle.package.asr import transcribe_audio

result = transcribe_audio("recordings/call_001.wav")
```

Set `ASR_MODEL_DIR` to an absolute checkpoint path before calling the
function. The only supported model is the local CTranslate2 checkpoint
`Systran/faster-whisper-large-v3` pinned to revision
`edaa852ec7e145841d8ffdb056a99866b5f0a478`. Download it to the external
location shown in the API guide, or set `ASR_MODEL_DIR` to another absolute
path. No Hugging Face token is required for the public model.

## Audio and returned fields

PyAV decodes one or two channels and resamples each channel independently to
16 kHz float audio. The original duration and silence remain on the timeline.
The function uses Vietnamese, beam size 5, word timestamps, and Silero VAD with
threshold `0.5`, minimum speech duration `0 ms`, minimum silence duration
`500 ms`, and `400 ms` speech padding. One model instance is cached per process; jobs and stereo
channels are serialized through one lock.

Each segment contains the original transcript fields plus `channel` and a
stable integer `id`. Every word contains a globally unique integer `id`,
timestamp fields, and probability when available. The result includes
`audio_metadata` and `channel_quality`. Quality reasons identify near-silent
channels, near-duplicate stereo signals, missing channel transcripts, and
mono input. The eligibility field is a heuristic quality flag, not speaker
identity or proof of independent speakers.

`diarization.status` is always `disabled`; no `speaker` identity is assigned.
Agent/customer mapping remains a backend decision.

## Save or call asynchronously

When `output_dir` is supplied, the function writes JSON, TXT, and SRT:

```python
result = transcribe_audio(
    "recordings/call_001.wav",
    output_dir="outputs/call_001",
)
```

For async backends, call the synchronous function in a worker thread:

```python
import asyncio
from whisper_bundle.package.asr import transcribe_audio

async def transcribe_for_request(audio_path: str) -> dict:
    return await asyncio.to_thread(transcribe_audio, audio_path)
```

Use the remote authenticated API in [README_API.md](../README_API.md) when
the backend should not host the model. Its response strips local model paths.
