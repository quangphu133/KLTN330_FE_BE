# Remote Whisper large-v3 API

The GPU computer hosts a small authenticated job API. The backend uploads an
audio file, receives a job ID, polls its status, and retrieves JSON, TXT, or
SRT output. The service runs one large-v3 model instance and one job at a
time.

## Prepare the model and environment

From the project root, download the public checkpoint at the pinned revision:

```powershell
hf download Systran/faster-whisper-large-v3 `
  --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 `
  --local-dir "$env:USERPROFILE\Models\faster-whisper-large-v3"
```

The download is about 3.09 GB and does not require a Hugging Face token. If
the model is kept elsewhere, set `ASR_MODEL_DIR` to its absolute path. Install
the locked service dependencies in the GPU environment before starting the
API.

Create the AI environment from the repository root if it does not already exist:

```powershell
py -3.11 -m venv .venv-asr-local
.\.venv-asr-local\Scripts\python.exe -m pip install -r .\api\requirements.txt
```

On the AI computer, confirm its Tailscale IPv4 with `tailscale ip -4`. Then
run the API from `api/`, so Python can import `whisper_bundle`. The model and
job-data locations below are absolute; keep the same data directory when
restarting an existing installation.

```powershell
$secret = Read-Host 'Enter the existing shared ASR API key' -AsSecureString
$env:ASR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
Set-Location .\api
$env:ASR_HOST = Read-Host 'AI computer Tailscale IPv4 (tailscale ip -4)'
$env:ASR_PORT = '8000'
$env:ASR_MODEL_DIR = "$env:USERPROFILE\Models\faster-whisper-large-v3"
if (-not [System.IO.Path]::IsPathRooted($env:ASR_MODEL_DIR)) { throw 'ASR_MODEL_DIR must be an absolute path.' }
if (-not (Test-Path -LiteralPath $env:ASR_MODEL_DIR -PathType Container)) { throw 'The model checkpoint directory was not found.' }
$env:ASR_DATA_DIR = Join-Path $env:LOCALAPPDATA 'KLTN330\asr_service_data_large_v3'
..\.venv-asr-local\Scripts\python.exe -m whisper_bundle.package.api_server
```

For a backend on another computer, bind to the AI computer's Tailscale IP
and allow port 8000 only from the laptop's Tailscale IP. Do not expose the
port to the public Internet. `ASR_API_KEY` remains local configuration and
must match the backend's existing setting.

## HTTP contract

Every endpoint requires:

```text
Authorization: Bearer <ASR_API_KEY>
```

- `GET /health` reports readiness, model, device, compute type, and queued job count.
- `POST /jobs` accepts a multipart field named `file` and returns HTTP 202 with a job ID.
- `GET /jobs/{job_id}` returns `queued`, `running`, `completed`, or `failed`.
- `GET /jobs/{job_id}/result` returns the transcript JSON.
- `GET /jobs/{job_id}/txt` and `/srt` return timestamped text; append `?download=1` to download.

The established status and result fields remain. The result includes
`model: "large-v3"`, `diarization.status: "disabled"`, `text`,
`segments`, `duration_seconds`, existing inference timings, and the added
`audio_metadata` and `channel_quality` objects. Each segment has a `channel`
integer; its `words` include globally unique integer IDs and word timestamps.
`model_path` is removed from public responses. Language is fixed to
Vietnamese, beam size to 5, and VAD is disabled.

Only mono or stereo inputs are accepted. Original sample rate, channel count,
and duration are reported. Stereo channels are resampled separately and
transcribed sequentially; merged segments are ordered by start time, then
channel. Silence is not cropped. The channel-quality flag reports silent or
near-constant channels, near-duplicate channels, and missing transcripts.
It does not infer which channel is the agent or customer and does not prove
that channels represent different people.

The default limits are 100 MiB per upload, 30 minutes per recording, 10
unfinished jobs, and seven days of job retention. Accepted formats are WAV,
MP3, M4A, FLAC, and OGG.

## Backend client

Copy `whisper_bundle/client` to the backend as `buzzasr_client` and install
its dependency:

```powershell
python -m pip install -r buzzasr_client\requirements.txt
```

```python
from buzzasr_client.api_client import submit_audio, wait_for_result

queued = submit_audio(base_url, "recordings/call_001.wav", api_key)
result = wait_for_result(base_url, queued["job_id"], api_key)
print(result["text"])
```

If polling times out, keep the original `job_id` and poll again rather than
submitting the same file a second time. The backend owns speaker and role
assignment.
