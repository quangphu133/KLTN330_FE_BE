# Business backend

An anonymized PostgreSQL schema and metrics snapshot is documented in
[`database/README.md`](database/README.md). Restore it only into the dedicated
empty database described there.

FastAPI nghiệp vụ chạy ở cổng `8001`. Backend quản lý người dùng, nhân viên,
project, checklist, từ điển, cuộc gọi, thống kê và điều phối job BuzzASR.

```powershell
cd backend
..\.venv-doan\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.db.init_db
python run.py
```

Use `requirements.lock.txt` instead of `requirements.txt` when reproducing the
dependency versions verified in this workspace.

Swagger UI: <http://127.0.0.1:8001/docs>

Nếu PostgreSQL đã từng được tạo bởi backend cũ trong thư mục gốc, chạy một lần
`migrations/001_merge_backends.sql` bằng pgAdmin hoặc `psql` trước khi khởi động.

Luồng upload chính là `POST /api/transcribe/upload`. Backend gửi audio tới
dịch vụ trong thư mục `../api`, theo dõi job rồi tạo bản ghi cuộc gọi.

If PostgreSQL was previously created by the backend in the repository root,
apply `migrations/001_merge_backends.sql` with pgAdmin or `psql` before the
initialization command above.

The backend connects to PostgreSQL through `psycopg2-binary`; keep the
`postgresql+psycopg2://` driver in `DATABASE_URL`. Start the ASR service on the
GPU computer, expose port 8000 only on the Tailscale interface, then set
`ASR_BASE_URL` in this backend's `.env` to `http://<AI_SERVER_IP>:8000` and
configure the same `ASR_API_KEY` on both computers. Check `/health` on the
backend and the authenticated ASR health endpoint before uploading a call.

Diarization được lưu trong `call_records.analysis_data`. Sau khi cài model
trong môi trường ASR riêng, API trả gợi ý vai trò tại
`GET /api/mediafile/{id}/result`; xác nhận bằng
`PUT /api/mediafile/{id}/speaker-roles` với JSON
`{"agentSpeakerId":"SPEAKER_00"}`. Chạy migration
`migrations/002_add_call_analysis_data.sql` một lần trước khi xử lý cuộc gọi mới.

## Nhân viên tổng đài và migration operator

Nhân viên tổng đài được quản lý trong bảng `users` với `role = 'telesales'`.
Các cuộc gọi và job gắn với tài khoản qua `telesale_id`; không còn API hoặc
danh mục Operator riêng. Các trường `operatorChannel` và `OnlyOperator` vẫn
được dùng để mô tả người tư vấn trong kết quả phân tích âm thanh.

Trước khi chạy `migrations/004_remove_operators.sql`, dừng upload và chờ toàn
bộ job `queued`/`running` hoàn tất. Sao lưu PostgreSQL và xác minh bản sao lưu
có thể đọc được. Migration chạy trong transaction và tự dừng nếu còn dòng
operator hoặc còn `operator_id` được gán trong `call_records`/`asr_jobs`.
Chỉ sau khi xác nhận các số đếm bằng 0 mới chạy migration trên database cần
triển khai. Để hoàn tác cấu trúc, chạy
`migrations/004_remove_operators_rollback.sql`; migration hoàn tác chỉ tạo lại
bảng/cột/khóa ngoại rỗng, không khôi phục dữ liệu Operator đã bị xóa.
