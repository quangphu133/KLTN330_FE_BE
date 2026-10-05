# Hướng dẫn backend sử dụng BuzzASR API

Tài liệu này dành cho backend chạy trên laptop và gọi dịch vụ BuzzASR trên máy GPU qua mạng Tailscale.

```text
backend -> Tailscale -> ASR API trên máy GPU -> BuzzASR CUDA FP16
```

## 1. Tạo virtual environment và chạy backend

Thực hiện trong PowerShell. Thay đường dẫn bằng thư mục api:

```powershell
Set-Location "C:\đường dẫn đến api"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install httpx pytest
```

Nếu PowerShell chặn `Activate.ps1`, chỉ mở quyền cho cửa sổ hiện tại rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Khi kích hoạt thành công, đầu dòng PowerShell có tiền tố `(.venv)`.

Backend dùng `app/main.py` làm entrypoint FastAPI, nhưng không chạy trực tiếp bằng `python app/main.py`. Chạy backend bằng Uvicorn:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Giữ cửa sổ này mở. Kiểm tra backend tại:

```text
http://127.0.0.1:8001/health
http://127.0.0.1:8001/docs
```

Vai trò các file chính:

| File | Cách sử dụng |
|---|---|
| `app/main.py` | Entry point FastAPI; chạy qua lệnh Uvicorn ở trên |
| `app/asr_client/api_client.py` | Thư viện gọi ASR API; được import, không chạy trực tiếp |
| `app/services/asr_service.py` | Submit, poll và lưu kết quả; được import, không chạy trực tiếp |
| `tests/test_api.py` | Chạy bằng pytest để kiểm tra backend |
| `run.py` | Không dùng trong cấu hình hai máy vì file này mặc định chiếm cổng 8000 |

Chạy test backend:

```powershell
python -m pytest tests\test_api.py -v
```

ASR API là tiến trình riêng trên máy có model. Chạy từ thư mục máy có model:

```powershell
.\.venv\Scripts\python.exe -m whisper_bundle.package.api_server
```

Khi kiểm thử luồng hoàn chỉnh, phải giữ ASR API trên máy GPU và backend cùng hoạt động.

## 2. Thông tin kết nối

ASR API mặc định chạy trên máy GPU tại cổng `8000`.

File `.env` của backend:

```dotenv
ASR_BASE_URL=http://GPU_TAILSCALE_IP:8000
ASR_API_KEY=REPLACE_WITH_THE_SHARED_SECRET
```

Quy tắc cấu hình:

- Thay `GPU_TAILSCALE_IP` bằng IPv4 Tailscale thật của máy GPU.
- `ASR_BASE_URL` không chứa `/health`, `/jobs` hoặc dấu `/` ở cuối.
- Không sử dụng `0.0.0.0` làm địa chỉ gọi từ backend. `0.0.0.0` chỉ dùng để ASR API lắng nghe trên máy GPU.
- Không đặt khóa thật trong mã nguồn, Git, frontend, URL, ảnh chụp màn hình hoặc tài liệu.

Kiểm tra kết nối từ laptop:

```powershell
Test-NetConnection GPU_TAILSCALE_IP -Port 8000
```

Kết quả phải có:

```text
TcpTestSucceeded : True
```

## 3. Kiểm tra trạng thái ASR API

PowerShell:

```powershell
$asrBaseUrl = "http://GPU_TAILSCALE_IP:8000"
$asrApiKey = $env:ASR_API_KEY

Invoke-RestMethod `
    -Uri "$asrBaseUrl/health" `
    -Headers @{ Authorization = "Bearer $asrApiKey" }
```

Kết quả hợp lệ:

```text
ready        : True
model        : buzzasr
device       : cuda
compute_type : float16
queued_jobs  : 0
```

`ready=True` xác nhận API sẵn sàng nhận job. Để xác nhận model thực sự phiên âm được, backend vẫn phải gửi một audio và chờ job hoàn tất.

## 4. Các endpoint

Mọi endpoint đều yêu cầu header:

```text
Authorization: Bearer <ASR_API_KEY>
```

| Method | Endpoint | Mục đích |
|---|---|---|
| `GET` | `/health` | Kiểm tra dịch vụ và số job đang chờ |
| `POST` | `/jobs` | Upload một audio bằng multipart field `file` |
| `GET` | `/jobs/{job_id}` | Đọc trạng thái job |
| `GET` | `/jobs/{job_id}/result` | Lấy transcript khi job hoàn tất |

Trạng thái job:

```text
queued -> running -> completed
                    \-> failed
```

`POST /jobs` trả HTTP `202` sau khi file và bản ghi job đã được lưu:

```json
{
  "job_id": "2a3f5f8b...",
  "status": "queued",
  "status_url": "http://gpu-host:8000/jobs/2a3f5f8b...",
  "result_url": "http://gpu-host:8000/jobs/2a3f5f8b.../result"
}
```

## 5. Cài Python client

Sao chép thư mục sau sang backend:

```text
whisper_bundle/client
```

Có thể đổi tên thư mục thành:

```text
buzzasr_client
```

Cài dependency:

```powershell
python -m pip install requests
```

Client cung cấp:

```python
submit_audio()
get_job()
wait_for_result()
AsrApiError
```

## 6. Luồng tích hợp được khuyến nghị

1. Backend nhận audio từ frontend hoặc hệ thống tổng đài.
2. Backend kiểm tra định dạng và dung lượng rồi lưu file tạm.
3. Backend gọi `submit_audio()`.
4. Backend lưu ngay `job_id` cùng `call_id` vào PostgreSQL.
5. Backend trả trạng thái `queued` cho frontend.
6. Worker nền gọi `get_job()` hoặc `wait_for_result()`.
7. Khi job `completed`, backend lấy `/result` và lưu transcript.
8. Backend xóa file tạm khi không còn cần thiết.

Không giữ HTTP request từ frontend mở trong toàn bộ thời gian model xử lý. Luồng job nền giúp tránh timeout của trình duyệt và reverse proxy.

## 7. Ánh xạ kết quả vào PostgreSQL

Các trường quan trọng từ ASR:

| Trường ASR | Dữ liệu backend đề xuất |
|---|---|
| `job_id` | `asr_jobs.job_id` |
| `status` | `asr_jobs.status` |
| `text` | `call_records.transcript` |
| `duration_seconds` | `call_records.audio_duration` |
| Toàn bộ JSON result | Cột JSON/JSONB hoặc kho lưu kết quả riêng |
| `segments` | Dữ liệu segment và timestamp |
| `segments[].words[]` | Word timestamps phục vụ đồng bộ waveform |

Nếu database cần giữ phần lẻ của giây, dùng kiểu `FLOAT` hoặc `NUMERIC` và không gọi `int()`.

Nên lưu toàn bộ result JSON để không làm mất word timestamps:

```python
transcript_json = result
transcript_text = result.get("text", "")
duration_seconds = result.get("duration_seconds", 0.0)
segments = result.get("segments", [])
```

## 8. Cấu trúc result

Ví dụ rút gọn:

```json
{
  "text": "Nội dung phiên âm hoàn chỉnh",
  "duration_seconds": 11.37,
  "segments": [
    {
      "start": 0.52,
      "end": 3.84,
      "text": "Nội dung một đoạn thoại",
      "words": [
        {
          "word": "Nội",
          "start": 0.52,
          "end": 0.78,
          "probability": 0.98
        }
      ]
    }
  ]
}
```

Timestamp dùng đơn vị giây tính từ đầu audio.

BuzzASR/Faster-Whisper hiện không gắn nhãn `agent` hoặc `customer`. Backend không được coi các segment là kết quả speaker diarization. Nếu cần phân biệt vai trò người nói, phải có bước diarization hoặc dữ liệu kênh audio riêng.

## 9. Giới hạn API

| Hạng mục | Giá trị mặc định |
|---|---:|
| Dung lượng tối đa | 100 MiB |
| Thời lượng tối đa | 30 phút |
| Số job chưa hoàn tất | 10 |
| Thời gian lưu kết quả | 7 ngày |
| Định dạng | WAV, MP3, M4A, FLAC, OGG |

Không gửi `.aac`; backend nên dùng cùng danh sách định dạng với ASR API.

GPU worker xử lý tuần tự để tránh nhiều job đồng thời chiếm VRAM. Nhiều request vẫn có thể được xếp hàng.

## 10. Xử lý lỗi

Lỗi API có cấu trúc:

```json
{
  "error": {
    "code": "queue_full",
    "message": "The ASR queue is full."
  }
}
```

| HTTP | Trường hợp thường gặp | Cách xử lý backend |
|---:|---|---|
| `400` | Request hoặc audio không hợp lệ | Trả lỗi validation cho client |
| `401` | Thiếu hoặc sai API key | Kiểm tra secret trên hai máy |
| `404` | Sai `job_id`, job hết hạn hoặc gọi sai URL | Kiểm tra URL và dữ liệu job |
| `409` | Kết quả chưa sẵn sàng hoặc job thất bại | Đọc trạng thái và `error` |
| `413` | File quá lớn | Từ chối trước khi upload |
| `415` | Định dạng không hỗ trợ | Chỉ nhận danh sách định dạng hợp lệ |
| `429` | Hàng đợi đầy | Giữ file và retry có kiểm soát sau |
| `500` | Lỗi lưu hoặc xử lý phía ASR | Ghi log theo `job_id`, báo vận hành |
| `503` | Model chưa sẵn sàng | Chờ health `ready=True` |

Nếu `wait_for_result()` timeout, job vẫn tồn tại trên máy GPU. Backend phải giữ `job_id` và poll lại; không upload lại audio.

Nếu ASR API khởi động lại:

- Job `queued` được xếp hàng lại.
- Job đang `running` được chuyển thành `failed` với code `server_restarted`.

## 11. Kiểm thử nhanh

Kiểm tra health:

```powershell
$asrBaseUrl = $env:ASR_BASE_URL.TrimEnd("/")
$headers = @{ Authorization = "Bearer $env:ASR_API_KEY" }
Invoke-RestMethod "$asrBaseUrl/health" -Headers $headers
```

Điều kiện đạt:

- `ready=True`.
- `model=buzzasr`.
- `device=cuda`.
- `compute_type=float16`.
- Upload audio trả HTTP `202` và có `job_id`.
- Job đi qua `queued`, `running`, `completed`.
- Result có transcript, `duration_seconds > 0` và word timestamps hợp lệ.
- PostgreSQL lưu đúng `job_id`, trạng thái, transcript và thời lượng.
