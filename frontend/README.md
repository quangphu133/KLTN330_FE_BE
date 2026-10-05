# Frontend

Next.js frontend chạy ở cổng `3000` và gọi FastAPI backend ở cổng `8001`.

```powershell
cd frontend
npm ci
npm run dev
```

Địa chỉ backend được cấu hình trong `.env.local`:

```dotenv
NEXT_PUBLIC_BASE_API_URL=http://127.0.0.1:8001/
```

Build production:

```powershell
npm run build
npm run start
```
