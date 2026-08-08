# Vue 前端

`frontend/` 是 Vue 3 + Vite 應用，包含病患問診、醫師工作區、規則中心與
SNOMED CT 查詢。根目錄的 `index.html`、`doctor.html` 是重構前的相容版本，
不再是主要開發入口。

## 服務版本

### v1.1.0 (2026-08-09)

- Production 與預設開發設定忽略 `backend`、`backendPort`、`fhir`、`directFhir`
  query override；開發 override 必須同時啟用 flag 並通過 exact-origin allowlist。
- Backend request 只在同源時攜帶 credentials；允許的跨來源開發 endpoint 明確使用
  `omit`，避免 session cookie 或身分識別資料被送往任意主機。
- FHIR 本次症狀分類改用獨立、窄版詞表與英文 token boundary，不再讓 `ENT` 等短詞
  誤判 Dementia／developmental／ventricular 等既往病史。
- 醫師病例畫面可為候選或歷史問卷路由顯示穩定 route／欄位標籤；生成問卷 catalog
  可由 backend exporter 以 `--check` 驗證同步。
- 13 項前端測試、OpenAPI 型別 drift 檢查與 Vite production build 均通過（Node 22）。

### v1.0.0（目前文件基線，2026-08-07）

此版號由 `devlog/` 的既有紀錄回溯建立，沒有對應的 Git tag；它描述
`frontend/` 開發版服務截至該日的功能集合，不代表已正式發布、部署或取得臨床
核准。此部署線與 `frontend-v2/` 的 doctor／patient 應用各自獨立演進。API
`/v1`、SQLite schema、RAG collection、疾病表與 Safety 規則另有自己的版本或
revision，不隨此前端版號連動。

此基線包含下列累積更新：

- **2026-07-27 — Vue 應用與多主訴問診基礎**
  - 建立 Vue 3、Vite 與 hash router 架構，提供病患端 `/#/` 與醫師端
    `/#/doctor`。
  - 將病患問診拆成聊天、輸入提示、人體疼痛圖與來源標籤等元件，支援文字、
    語音、單選、複選、自由補充、日期、持續時間及正／背面疼痛位置。
  - 接入胸痛、頭痛與腹痛動態問卷及 FHIR 預填；已由 FHIR 取得的資料可略過，
    身分證字號只用於受控測試環境中的 FHIR 查詢。
  - 建立醫師端病例與 AI 報告檢視，並保留 D-ID Avatar 與純文字問診模式。
- **2026-07-28 — 病患流程與醫師工作台重構**
  - 元件化開始問診、Avatar 設定、結構化問卷、疼痛位置及 AMIE 軌跡面板，
    並擴充前後視圖的身體疼痛區域。
  - 新增醫師病例搜尋、分頁、選取及二次確認刪除，並強化病歷時間軸、臨床
    evidence、FHIR coding、術語與背景摘要狀態的呈現。
  - 更新後端、FHIR、臨床病歷及術語服務封裝與前端測試。
- **2026-07-29 — 規則治理、SNOMED CT 與 SMART 整合**
  - 新增醫師端規則中心，可分類、搜尋及編輯既有 Safety 規則；語意特徵以
    catalog 勾選，發布前仍需完整性檢查、理由與指定確認文字。
  - 新增 SNOMED CT 查詢頁、分頁與錯誤處理，並在疾病方向顯示已驗證的 coding。
  - SMART OAuth 完成後可返回病患問診，讀取 launch-context Patient 與
    `$everything` 預填資料；FHIR access token 不送往 `/chat`、RAG 或外部模型。
  - 改善多主訴已知資訊預填與依病人情境隱藏不適用的問卷選項。
- **2026-08-04 — `/v1` API 與完整規則治理介面**
  - 前端 API client 切換至 `/v1`，加入 OpenAPI TypeScript 型別產生與同步檢查。
  - 將規則中心擴充為疾病票數、ClinicalFact 與 Safety 三個治理介面，支援
    payload 驗證、版本衝突提示、審查資料及發布確認流程。
  - 醫師病例卡新增獨立 EMR 摘要區塊，避免在結構化報告中重複呈現相同內容。
- **2026-08-05 — 候選漏斗與跨日期病例識別**
  - 將大型規則治理畫面拆成選擇器、編輯器、發布面板與 composable，並補上
    payload 正規化、變更偵測、驗證及 filter reset 測試。
  - Clinical Evidence 與 debug trace 可呈現確定性候選漏斗及選題依據；病患端
    debug payload 不暴露疾病名稱、票數或完整排名。
  - 病例卡、載入、刪除及 active state 改用「看診日期＋掛號編號」的 composite
    ID，並把跨日期同號衝突轉為可操作提示。
- **2026-08-07 — 可回上一題、摘要格式與本機語音／Avatar**
  - 結構化問卷支援取消選項、以「其他」文字取代舊選項及返回上一題重新作答；
    body pain map 的左右標示亦提高辨識度。
  - 病例卡將舊摘要相容轉換為固定兩行格式：第一行為主要病況，第二行為兩句
    其他 EMR 病史。
  - 預設接入本機 Breeze-ASR-26 語音辨識，以及 CosyVoice3 + MuseTalk Avatar；
    亦可切換鎖定版本、由本地 bundle 延遲載入的 D-ID provider。
  - loopback-only 開發驗證 bypass 僅接受直接本機連線，正式設定預設關閉。

## 主要目錄

| 路徑 | 用途 |
| --- | --- |
| `src/components/` | 共用 UI 元件 |
| `src/composables/` | 本地／D-ID Avatar provider 狀態與操作 |
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

前端預設使用目前網頁 hostname 與 port `8000` 連接 FastAPI。正式環境與預設設定
會忽略 URL query 的 backend／FHIR 端點覆寫，避免惡意連結改變病歷資料目的地。
只有本機開發需要臨時切換端點時，才可同時啟用開關並列出允許 origin：

```dotenv
VITE_ENABLE_BACKEND_QUERY_OVERRIDE=true
VITE_BACKEND_QUERY_OVERRIDE_ORIGINS=http://localhost:9000,http://192.168.1.20:9000
VITE_ENABLE_FHIR_QUERY_OVERRIDE=true
VITE_FHIR_QUERY_OVERRIDE_ORIGINS=http://localhost:8080
```

啟用後可使用：

```text
http://localhost:5173/?backendPort=9000#/
http://localhost:5173/?backend=http://192.168.1.20:9000#/
```

跨 origin backend 即使在 allowlist 內也不會攜帶 cookie；需要病患 session 的環境
應使用同源 reverse proxy。固定端點則由 `.env` 設定：

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

## Avatar providers

病患端支援兩種可切換的 Avatar，預設為完全本地：

- `local`：Fun-CosyVoice3-0.5B-2512 + MuseTalk 1.5，由後端 GPU 服務產生。
- `did`：保留原本 D-ID Agent SDK；Client Key 與 Agent ID 可在設定面板輸入。

D-ID browser SDK 以鎖定版本的 `@d-id/client-sdk` npm dependency 隨應用建置，
並在選用 D-ID 時才從本地 JavaScript chunk 延遲載入；瀏覽器不會再向第三方 CDN
動態下載 SDK。

可在 `.env` 選擇預設 provider：

```dotenv
VITE_AVATAR_PROVIDER=local
VITE_DID_CLIENT_KEY=
VITE_DID_AGENT_ID=
```

未啟用時仍可使用純文字或語音輸入。所有 `VITE_*` 值都會在 build-time
寫入公開的瀏覽器 JavaScript；因此建議在 UI 輸入 D-ID 資料（只存於頁面記憶體）。
若必須預先設定，只能使用由 [D-ID Studio](https://studio.d-id.com) 建立、限制部署
網域的瀏覽器／Embed Key，絕不可放伺服器私鑰。

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
