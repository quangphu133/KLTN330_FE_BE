# Whisper large-v3 API

This directory contains the standalone authenticated API distribution. It
does not include model weights. The service supports only
`Systran/faster-whisper-large-v3` at revision
`edaa852ec7e145841d8ffdb056a99866b5f0a478`.

Download the public checkpoint on the AI computer (no Hugging Face token is
required):

```powershell
hf download Systran/faster-whisper-large-v3 `
  --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 `
  --local-dir models\large-v3
```

Create a dedicated environment and install the locked dependencies:

```powershell
py -3.11 -m venv .venv-asr-local
.\.venv-asr-local\Scripts\python.exe -m pip install -r .\api\requirements.txt
```

Run the standalone API from `api/`. Enter the absolute model directory and
this AI machine's Tailscale IPv4 address. The key is prompted securely and
kept in this PowerShell process environment:

```powershell
Set-Location .\api
$secret = Read-Host 'Enter the existing shared ASR key' -AsSecureString
$env:ASR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
$env:ASR_MODEL_DIR = Read-Host 'Enter the absolute large-v3 checkpoint path'
if (-not [System.IO.Path]::IsPathRooted($env:ASR_MODEL_DIR)) { throw 'ASR_MODEL_DIR must be an absolute path.' }
if (-not (Test-Path -LiteralPath $env:ASR_MODEL_DIR -PathType Container)) { throw 'The model checkpoint directory was not found.' }
$env:ASR_HOST = Read-Host 'Enter this AI machine Tailscale IPv4 (tailscale ip -4)'
$env:ASR_PORT = '8000'
$env:ASR_DATA_DIR = Join-Path $env:LOCALAPPDATA 'KLTN330\asr_service_data'
..\.venv-asr-local\Scripts\python.exe -m whisper_bundle.package.api_server
```

Keep the same `ASR_DATA_DIR` between restarts to retain job history. For an
existing installation, keep its current data directory. For a laptop on a
different machine, set backend `ASR_BASE_URL` to
`http://<AI_TAILSCALE_IP>:8000`; do not add `/health` or a trailing slash.

Every endpoint requires Bearer authentication. The API retains the existing
health, upload, status, result, TXT, and SRT routes. It accepts mono/stereo,
keeps the full timeline, disables VAD, and transcribes stereo channels
sequentially. Results include channel metadata and native signal-quality
flags, but the AI does not assign speaker identities or roles. Noise/music
may still yield nonempty text; the backend should use manual review whenever
channel or transcript quality is uncertain.

See [the API contract](whisper_bundle/README_API.md) and
[the backend integration guide](whisper_bundle/package/README_BACKEND.md).
