# Hệ thống hậu kiểm và đánh giá cuộc gọi

Mã nguồn web và backend phục vụ khóa luận: tải bản ghi cuộc gọi, phiên âm tiếng Việt, phân tách người nói, xác nhận vai trò nhân viên/khách hàng và đánh giá tuân thủ theo quy tắc hiện có.

- **Web và backend:** [quangphu133/KLTN330_FE_BE](https://github.com/quangphu133/KLTN330_FE_BE).
- **Android App dành cho nhân viên:** [quangphu133/KNTN330_DT](https://github.com/quangphu133/KNTN330_DT). Đây là repository riêng, không nằm trong thư mục `frontend/`.
- **Model AI:** [Whisper large-v3 trên Faster-Whisper](https://huggingface.co/Systran/faster-whisper-large-v3), dùng [thư viện Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) và revision cố định `edaa852ec7e145841d8ffdb056a99866b5f0a478`. Model được tải riêng, không nằm trong repo.

## 1. Cấu trúc và luồng kết nối

| Thành phần | Thư mục | Vai trò | Cổng local |
| --- | --- | --- | --- |
| Web Next.js | `frontend/` | Quản lý và xem kết quả cuộc gọi | `3000` |
| Backend FastAPI | `backend/` | Tài khoản, dữ liệu nghiệp vụ, lưu audio, điều phối AI | `8001` |
| Whisper ASR API | `api/` | Nhận yêu cầu từ backend và chạy Whisper large-v3 đã được tải riêng; không chứa model | `8000` |
| PostgreSQL | Dịch vụ cài riêng | Lưu dữ liệu nghiệp vụ | `5432` mặc định |

```text
Web / App -> Backend :8001 -> Whisper ASR API :8000
                  |
             PostgreSQL
```

**Repository chỉ cung cấp mã nguồn tích hợp.** Thư mục `api/` chứa API và client cho Whisper ASR, không chứa checkpoint large-v3. Tải checkpoint công khai theo revision nêu trên và cấu hình `ASR_MODEL_DIR` tới thư mục checkpoint tuyệt đối. Hugging Face token không bắt buộc.

**Database cũng cần tự chuẩn bị:** repo có model dữ liệu ORM và migration SQL trong `backend/`, không kèm bản sao lưu dữ liệu, tài khoản đăng nhập hay dữ liệu cuộc gọi thực tế. Người dùng tự cài PostgreSQL, tạo database và khởi tạo bảng theo phần 3. Việc kết nối database nghiệp vụ do `backend/` thực hiện.

## 2. Chuẩn bị và lấy mã nguồn

Hướng dẫn dùng Windows và **PowerShell**. Cần Git, Python 3.11, Node.js 20 trở lên với npm, PostgreSQL đang hoạt động và công cụ `psql`/`pg_dump` nếu thao tác database trong terminal. Có thể dùng pgAdmin cho các thao tác SQL tương ứng.

Máy chỉ chạy web/backend. Máy AI cần checkpoint CTranslate2 của Whisper large-v3 và môi trường GPU tương thích.

```powershell
git clone https://github.com/quangphu133/KLTN330_FE_BE.git
cd KLTN330_FE_BE
py -3.11 -m venv .venv-doan
.\.venv-doan\Scripts\python.exe -m pip install -r .\backend\requirements.lock.txt
```

Dùng trực tiếp Python của môi trường ảo nên không bắt buộc chạy `Activate.ps1`. `requirements.lock.txt` ghi các phiên bản backend đã chốt; `requirements.txt` khai báo phụ thuộc trực tiếp. Cài thư viện AI vào môi trường riêng.

## 3. Cấu hình backend và PostgreSQL

Từ thư mục gốc repo, sao chép mẫu nếu chưa có cấu hình local:

```powershell
if (-not (Test-Path .\backend\.env)) {
    Copy-Item .\backend\.env.example .\backend\.env
}
```

Mở `backend/.env`, thay các giá trị giữ chỗ bằng cấu hình của máy:

```dotenv
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_DB_PASSWORD@127.0.0.1:5432/do_an_db
APP_ENV=development
SECRET_KEY=REPLACE_WITH_A_LONG_RANDOM_SECRET
ACCESS_TOKEN_EXPIRE_MINUTES=1440
ASR_BASE_URL=http://127.0.0.1:8000
ASR_API_KEY=REPLACE_WITH_THE_SAME_KEY_AS_THE_AI_SERVER
```

- Tạo database PostgreSQL trước; `init_db` tạo bảng, không tạo database PostgreSQL.
- Mật khẩu có ký tự đặc biệt trong `DATABASE_URL` cần được mã hóa URL.
- `SECRET_KEY` ký JWT đăng nhập. `ASR_API_KEY` xác thực backend với AI và phải giống nhau ở hai phía.
- Nếu AI chạy trên máy khác, đổi `ASR_BASE_URL` sang địa chỉ LAN/Tailscale thực tế của máy AI.

### Database mới

Ví dụ tạo database bằng `psql` (bỏ qua nếu đã tạo bằng pgAdmin), sau đó khởi tạo bảng:

```powershell
psql -h 127.0.0.1 -U postgres -d postgres -c 'CREATE DATABASE do_an_db;'
cd backend
..\.venv-doan\Scripts\python.exe -m app.db.init_db
```

Lệnh khởi tạo tạo bảng còn thiếu và thêm các mục từ điển Regex mặc định. Nó không tự tạo tài khoản đăng nhập và không tự nâng cấp cột trong bảng cũ.

### Database đã có dữ liệu

Sao lưu trước khi thay đổi schema. Các lệnh dưới chạy từ `KLTN330_FE_BE/backend`; điều chỉnh host, user và database theo máy:

```powershell
$backupFile = "backup-before-migration-$(Get-Date -Format 'yyyyMMdd-HHmmss').dump"
pg_dump -Fc -h 127.0.0.1 -U postgres -d do_an_db -f $backupFile
```

Chỉ tiếp tục khi sao lưu thành công; giữ bản sao ngoài repository.

- `migrations/001_merge_backends.sql`: dành cho database của backend cũ ở thư mục gốc, có các bảng `users`, `call_records`, `asr_jobs` cần bổ sung cột tương thích.
- `migrations/002_add_call_analysis_data.sql`: bổ sung cột lưu phiên âm, diarization và vai trò người nói cho bảng `call_records` cũ.
- `migrations/003_add_call_notifications.sql`: tạo bảng và chỉ mục thông báo cuộc gọi cho web/app.
- `migrations/004_remove_operators.sql`: bỏ danh mục Operator cũ, dùng tài khoản `users` với `role = 'telesales'` và liên kết `telesale_id`. Dừng upload, chờ các job kết thúc và kiểm tra dữ liệu trước khi chạy; migration tự dừng nếu còn Operator hoặc tham chiếu `operator_id`, không tự đoán tài khoản thay thế.
- `migrations/005_add_violation_deduction.sql`: bổ sung `violations.deduction` và đồng bộ nội dung thông báo hoàn tất cho các cuộc gọi đã có điểm. Migration này cần thiết cho phiên bản backend hiện tại; `app.db.init_db` không thêm cột vào bảng đã tồn tại.

Chọn migration phù hợp với schema hiện tại; không chạy `001` trên database rỗng:

```powershell
psql -h 127.0.0.1 -U postgres -d do_an_db -v ON_ERROR_STOP=1 -f .\migrations\001_merge_backends.sql
psql -h 127.0.0.1 -U postgres -d do_an_db -v ON_ERROR_STOP=1 -f .\migrations\002_add_call_analysis_data.sql
psql -h 127.0.0.1 -U postgres -d do_an_db -v ON_ERROR_STOP=1 -f .\migrations\003_add_call_notifications.sql
psql -h 127.0.0.1 -U postgres -d do_an_db -v ON_ERROR_STOP=1 -f .\migrations\004_remove_operators.sql
psql -h 127.0.0.1 -U postgres -d do_an_db -v ON_ERROR_STOP=1 -f .\migrations\005_add_violation_deduction.sql
```

Chạy các migration phù hợp với schema hiện tại; dòng `005` là migration cần thiết cho backend hiện tại. Các lệnh trên chạy từ thư mục `backend/`. Không dùng `app.db.init_db` như migration cho database đã có dữ liệu: lệnh đó tạo bảng còn thiếu và seed từ điển Regex nhưng không thêm cột cho bảng cũ. Với database mới, xem mục trên; không xóa/reset dữ liệu để xử lý thiếu migration. Migration `001` và `002` chưa có script rollback đi kèm. Khi cần hoàn tác, phục hồi bản sao lưu vào database riêng, kiểm tra dữ liệu rồi mới đổi `DATABASE_URL`. Migration `004` có script rollback chỉ tạo lại cấu trúc Operator rỗng. Migration `005` giữ lại cột deduction khi hoàn tác code vì lịch sử khấu trừ không thể khôi phục. Với thông báo, file `003_add_call_notifications_rollback.sql` chỉ hướng dẫn hoàn tác code và giữ nguyên bảng/lịch sử thông báo. Xem thêm [hướng dẫn backend](backend/README.md).

## 4. Chạy backend và tạo tài khoản local

Mở PowerShell tại thư mục gốc repo rồi chạy. Nhập IP Tailscale của máy AI và cùng khóa ASR hiện có; khóa chỉ được đặt trong môi trường của tiến trình này, không ghi vào mã nguồn:

```powershell
Set-Location .\backend
$aiTailnetIP = Read-Host 'AI machine Tailscale IPv4 (tailscale ip -4)'
$env:ASR_BASE_URL = "http://$($aiTailnetIP):8000"
$secret = Read-Host 'Enter the existing shared ASR API key' -AsSecureString
$env:ASR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
& '..\.venv-doan\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

`ASR_BASE_URL` chỉ là địa chỉ gốc, không thêm `/health`, `/jobs`, `/api` hoặc dấu `/` cuối. Backend gọi Whisper API bằng `ASR_BASE_URL` và `ASR_API_KEY`. Các biến môi trường của PowerShell hiện tại được ưu tiên hơn giá trị cùng tên trong `backend/.env`.

- Health: <http://127.0.0.1:8001/health>.
- Swagger: <http://127.0.0.1:8001/docs>.
- Có thể dùng `..\.venv-doan\Scripts\python.exe run.py` để chạy chế độ phát triển có reload và tự mở Swagger.

API `POST /api/users/` yêu cầu tài khoản admin đã đăng nhập. Với database mới chưa có admin, mở terminal khác tại `KLTN330_FE_BE/backend` và tạo admin đầu tiên bằng cấu hình database local:

```powershell
..\.venv-doan\Scripts\python.exe -X utf8 -c @'
from getpass import getpass
from app.db.database import SessionLocal
from app.models.user import User
from app.schemas.user_schema import UserCreate
from app.services.user_service import UserService

with SessionLocal() as db:
    if db.query(User).filter(User.role == "admin").first():
        raise SystemExit("An admin account already exists. Sign in to manage accounts.")
    account = UserCreate(
        email=input("Admin email: ").strip(),
        full_name=input("Full name: ").strip(),
        password=getpass("Password (at least 6 characters): "),
        role="admin",
    )
    user = UserService.create(db, account)
    print(f"Created admin account: {user.email}")
'@
```

Sau đó đăng nhập qua web hoặc `POST /api/auth/signin`. Admin tạo nhân viên tại trang **Nhân viên tổng đài**, hoặc gọi `POST /api/users/` kèm Bearer token. Repo không kèm tài khoản/mật khẩu dùng chung. Nhân viên truy cập cuộc gọi và job thuộc tài khoản của mình; các API quản lý yêu cầu quyền admin. Khi triển khai ngoài môi trường local, cấu hình HTTPS và kiểm thử quyền truy cập với tài khoản thực tế.

## 5. Chạy giao diện web

Mở terminal khác từ thư mục gốc repo:

```powershell
cd frontend
npm ci
```

Tạo `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_BASE_API_URL=http://127.0.0.1:8001/
```

**Giữ dấu `/` cuối URL và không thêm `/api`.** Một số lời gọi web nối trực tiếp URL gốc với `api/...`, gồm endpoint phát audio. Khởi động lại Next.js sau khi đổi file môi trường.

```powershell
npm run dev
```

Mở <http://localhost:3000/auth/sign-in> và đăng nhập bằng tài khoản đã tạo. Chế độ demo của web có dữ liệu mô phỏng; kiểm thử backend/AI cần dùng tài khoản thật trong database.

## 6. Whisper large-v3 API trên máy AI

Mã API nằm trong `api/whisper_bundle/`; repository không chứa checkpoint. API dùng checkpoint Faster-Whisper large-v3 công khai của Systran tại revision cố định `edaa852ec7e145841d8ffdb056a99866b5f0a478`. Tải checkpoint một lần trên máy AI; token Hugging Face không cần thiết cho model công khai. API chạy bằng các file đã tải trong `ASR_MODEL_DIR`, không tải model từ Hugging Face khi khởi động.

Ví dụ tải model về một vị trí ngoài repository:

```powershell
hf download Systran/faster-whisper-large-v3 `
  --revision edaa852ec7e145841d8ffdb056a99866b5f0a478 `
  --local-dir "$env:USERPROFILE\Models\faster-whisper-large-v3"
```

Nếu chưa có môi trường Python riêng cho AI, tạo môi trường tại gốc repo và cài phụ thuộc của API:

```powershell
py -3.11 -m venv .venv-asr-local
.\.venv-asr-local\Scripts\python.exe -m pip install -r .\api\requirements.txt
```

Khởi động API từ gốc repo. Xem IP bằng `tailscale ip -4` trên máy AI rồi nhập địa chỉ đó để API chỉ bind vào giao diện Tailscale:

```powershell
$aiTailnetIP = Read-Host 'AI machine Tailscale IPv4 (tailscale ip -4)'
$secret = Read-Host 'Enter the existing shared ASR API key' -AsSecureString
$env:ASR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
$env:ASR_HOST = $aiTailnetIP
$env:ASR_PORT = '8000'
$env:ASR_MODEL_DIR = "$env:USERPROFILE\Models\faster-whisper-large-v3"
if (-not [System.IO.Path]::IsPathRooted($env:ASR_MODEL_DIR)) { throw 'ASR_MODEL_DIR must be an absolute path.' }
if (-not (Test-Path -LiteralPath $env:ASR_MODEL_DIR -PathType Container)) { throw 'The model checkpoint directory was not found.' }
$env:ASR_DATA_DIR = Join-Path $env:LOCALAPPDATA 'KLTN330\asr_service_data'
Set-Location .\api
..\.venv-asr-local\Scripts\python.exe -m whisper_bundle.package.api_server
```

Keep the existing `ASR_DATA_DIR` when restarting an installation with saved jobs. Do not add the API key to source, Git, frontend, or Android files. All API endpoints, including health, require Bearer authentication. The API accepts mono/stereo audio, retains the full timeline, disables VAD, and processes stereo channels sequentially. It reports channel-quality flags but does not assign agent/customer identities; role assignment remains in the backend workflow.

Kiểm tra API từ PowerShell trên máy laptop. Nhập IP Tailscale của máy AI và cùng khóa dùng trên máy AI:

```powershell
$aiTailnetIP = Read-Host 'AI machine Tailscale IPv4 (tailscale ip -4)'
tailscale ping $aiTailnetIP
Test-NetConnection $aiTailnetIP -Port 8000
$secret = Read-Host 'Enter the existing shared ASR API key' -AsSecureString
$env:ASR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret
$asrBaseUrl = "http://$($aiTailnetIP):8000"
$headers = @{ Authorization = "Bearer $env:ASR_API_KEY" }
Invoke-RestMethod -Uri "$asrBaseUrl/health" -Headers $headers
```

Kết quả cần báo `ready=true`, `model=large-v3`, `device=cuda`, `compute_type=float16`. Nếu `tailscale ping` thành công nhưng TCP 8000 không kết nối được, kiểm tra API đang chạy và firewall trên máy AI. Thông thường Tailscale hoạt động với firewall hiện có; nếu cần luật inbound, chỉ cho TCP 8000 từ IP Tailscale laptop tới IP Tailscale máy AI. [Tailscale CLI](https://tailscale.com/kb/1080/cli) · [Tailscale firewall guidance](https://tailscale.com/kb/1181/firewalls)

Ví dụ tạo luật giới hạn địa chỉ, chỉ chạy trên máy AI trong PowerShell mở bằng quyền Administrator khi đã xác định đúng IP của cả hai máy:

```powershell
$aiTailnetIP = Read-Host 'AI machine Tailscale IPv4'
$laptopTailnetIP = Read-Host 'Laptop Tailscale IPv4'
New-NetFirewallRule -DisplayName 'Whisper API TCP 8000 from laptop Tailscale IP' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $aiTailnetIP -LocalPort 8000 -RemoteAddress $laptopTailnetIP -Profile Any
```

Verify readiness and then submit a test file through the existing upload
flow. `ready=true` alone does not verify transcription; poll the accepted job
through `completed` and inspect the returned transcript and timestamps.

## 7. Kiểm thử một cuộc gọi

1. Khởi động PostgreSQL, AI, backend và web; kiểm tra health của hai API. Với máy cài mới, PostgreSQL và `DATABASE_URL` phải được cấu hình trước; không chạy lệnh khởi tạo/seed trên database đã có dữ liệu.
2. Đăng nhập tài khoản thật, tải audio qua `POST /api/transcribe/upload` (web hoặc Swagger). WAV, MP3, M4A, OGG, FLAC được cả backend và AI chấp nhận. Backend mặc định giới hạn 50 MB, AI mặc định giới hạn 30 phút.
3. Theo dõi `GET /api/transcribe/{job_id}/status` tới `completed` hoặc `failed`; đọc `error_message` nếu có.
4. Dùng `call_record_id` để đọc `GET /api/mediafile/{id}/result` và nghe `GET /api/mediafile/{id}/stream`.
5. AI không nhận dạng speaker hoặc vai trò agent/customer. Dùng quy trình xác nhận vai trò hiện có trong backend; không suy ra danh tính từ thứ tự channel. Kiểm tra `channel_quality` và transcript stereo trước khi dùng dữ liệu.
6. Đọc `roleMapping`, `keywordsSearchResult.regions` và `complianceScore` trong kết quả mediafile; `GET /api/calls/{id}` dùng tên trường `compliance_score`. Điểm chưa có là `null`, không phải 0. Điểm tuân thủ dựa trên Regex trong `backend/app/services/rule_service.py`, không phải điểm cảm xúc hoặc một checklist tùy ý trên giao diện.

Nếu AI ngoại tuyến, backend có thể lưu audio cùng job thất bại; HTTP 202 chỉ cho biết đã tiếp nhận, không chứng minh AI phân tích thành công. Cờ chất lượng không phải bộ phát hiện speech: nhiễu hoặc nhạc vẫn có thể tạo transcript không rỗng. Khi không chắc, backend cần giữ bước kiểm tra/xác nhận thủ công.

## 8. Kết nối Android app

Hướng dẫn Flutter nằm tại [KNTN330_DT](https://github.com/quangphu133/KNTN330_DT). `API_BASE_URL` của app là địa chỉ gốc backend, không thêm `/api`:

| Thiết bị | `API_BASE_URL` |
| --- | --- |
| Android Emulator trên máy backend | `http://10.0.2.2:8001` |
| Điện thoại thật cùng LAN | `http://<IP_LAN_MAY_BACKEND>:8001` |

Với điện thoại thật, backend cần bind IP LAN hoặc `0.0.0.0`, firewall cho phép thiết bị thử nghiệm truy cập cổng `8001`. `localhost` trên điện thoại là chính điện thoại. HTTP chỉ phục vụ demo debug; bản release dùng HTTPS theo hướng dẫn repo app.

Backend hiện có `GET /api/analytics/me`, `GET /api/transcribe/`, `GET /api/notifications/` và `PATCH /api/notifications/{id}/read` cho app. Web và app dùng chung tài khoản nhân viên trong `users` và chủ sở hữu cuộc gọi qua `telesale_id`. Với database cũ, kiểm tra migration `003`/`004` trước khi chạy phiên bản này. Kiểm thử upload, xác nhận người nói, thông báo và nghe audio bằng cùng tài khoản/cùng ID cuộc gọi để xác nhận kết nối thực tế giữa hai repo.

## 9. Kiểm tra mã nguồn

Backend, từ thư mục gốc repo:

```powershell
cd backend
..\.venv-doan\Scripts\python.exe -m pytest
```

Bộ test cấu hình SQLite và thư mục upload tạm riêng.

Frontend, mở terminal khác từ thư mục gốc repo:

```powershell
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

Sau khi build thành công, dùng `npm run start` để chạy bản build.
