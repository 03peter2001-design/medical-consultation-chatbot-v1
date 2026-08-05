# Vue 前端

`frontend/` 是 Vue 3 + Vite 應用，包含病患問診、醫師工作區、規則中心與
SNOMED CT 查詢。根目錄的 `index.html`、`doctor.html` 是重構前的相容版本，
不再是主要開發入口。

## 主要目錄

| 路徑 | 用途 |
| --- | --- |
| `src/components/` | 共用 UI 元件 |
| `src/composables/` | D-ID Avatar 等狀態與操作 |
| `src/services/` | 後端 API、FHIR 與連線設定 |
| `src/views/` | 病患端、醫師端與術語頁面 |
| `src/generated/` | 由 OpenAPI 產生的型別，不手動編輯 |
| `tests/` | Node 單元測試 |

## 安裝與啟動

需求為 Node.js 18+：

```bash
npm install
npm run dev
```

Vite 會顯示實際網址，預設入口為：

- `http://localhost:5173/#/`：病患端
- `http://localhost:5173/#/doctor`：醫師端
- `http://localhost:5173/#/doctor/terminology/snomed`：SNOMED CT 查詢

其他指令：

```bash
npm test
npm run build
npm run preview
npm run api:types
npm run api:check
```

正式建置輸出位於 `dist/`。

## 後端連線

前端預設使用目前網頁 hostname 與 port `8000` 連接 FastAPI。可用 URL query
暫時覆寫：

```text
http://localhost:5173/?backendPort=9000#/
http://localhost:5173/?backend=http://192.168.1.20:9000#/
```

切換至醫師端時設定會保留。也可由 `.env` 固定設定：

```bash
cp .env.example .env
```

```dotenv
VITE_BACKEND_PORT=9000
# 正式同源 reverse proxy 可改用：
# VITE_BACKEND_BASE_URL=/api
```

若從手機或其他電腦連線，後端需監聽所有介面，並確認防火牆允許該 port：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

發生「無法連線到後端」時，先開啟 `http://後端主機:8000/v1/health` 確認服務
可達，再檢查 frontend 的 backend URL 設定。

## 病患端與醫師端

病患端會收集自由主訴、FHIR 尚未提供的基本資料與病史，再依主訴進入胸痛、
頭痛或腹痛問卷。選擇題支援單選、複選、自由補充與正／背面人體疼痛位置標記。

醫師端可瀏覽、分頁及依姓名、問診編號或主訴搜尋病例；點選後可查看疼痛位置、
約 300 字速覽摘要、固定疾病表排名與六段式分析。病例需經二次確認才會永久
刪除。問診編號 `00000` 是內建的假病人展示資料。

規則中心的實際治理與權限邏輯在後端，請見
[../backend/README.md](../backend/README.md#醫師端規則中心)。

## FHIR 直接連線（僅限開發／測試）

使用本機 HAPI Server 時，可在 `.env` 設定：

```dotenv
VITE_ENABLE_DIRECT_FHIR=true
VITE_FHIR_BASE_URL=http://localhost:8080/fhir
```

前端會用台灣身分證 identifier system `http://www.moi.gov.tw` 查詢
`Patient.identifier`，找到唯一病人後讀取 `Patient/{id}/$everything`，再將資料
映射至問卷預填。HAPI 必須允許 Vite 開發網址的 CORS。

測試 Bundle 位於 `../backend/fhir_samples/`。身分證直接查詢只適用本機或受控
測試環境；正式環境必須使用 SMART on FHIR OAuth、最小權限 scope、核准的
client registration 與稽核。完整 SMART 流程請見
[../smart-app/README.md](../smart-app/README.md)。

## D-ID 虛擬數位人

病患端的「D-ID 設定」可填入：

- Client Key：由 [D-ID Studio](https://studio.d-id.com) 取得
- Agent ID：在 D-ID Studio 建立 Agent 後取得

未設定時仍可使用純文字或語音輸入，只是不會顯示虛擬數位人說話效果。

## OpenAPI 型別

後端的版本控制規格位於 `../docs/openapi.json`。API model 或 route 變更後：

```bash
cd ../backend
python -m scripts.export_openapi
python -m scripts.export_openapi --check

cd ../frontend
npm run api:types
npm run api:check
```

請勿手動修改 `src/generated/api.d.ts`。
