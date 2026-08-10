# Vue 前端

`frontend/` 是 Vue 3 + Vite 應用，包含病患問診、醫師工作區、規則中心與
SNOMED CT 查詢。根目錄的 `index.html`、`doctor.html` 是重構前的相容版本，
不再是主要開發入口。

## 服務版本

### v1.6.0 (2026-08-10)

- 本地 Avatar 檢查服務、warm-up 載入 Breeze／CosyVoice／MuseTalk，以及產生語音
  影片期間，設定抽屜與中央醫師舞台都顯示目前階段、轉動指示與等待說明，避免長時間
  GPU 載入看似沒有反應；狀態區使用 `aria-live`／`aria-busy` 通知輔助科技。
- 錄音期間使用既有 Web Audio analyser 的 RMS 音量驅動七段即時波形；高於語音
  閾值後明確顯示「已收到聲音」。手動錄音與 Avatar 自動錄音都有視覺回饋，但只有
  Avatar 自動錄音維持說話後靜音 5 秒自動送交辨識的行為。
- 波形在窄螢幕縮成圖像提示，保留文字輸入、停止錄音與送出按鈕空間；降低動態偏好
  會停用 spinner 動畫與 waveform transition。

### v1.5.0 (2026-08-10)

- 本機 Avatar 設定新增「醫生說話語言」，可自由切換國語與閩南語；選擇值隨每次
  合成請求傳入，中央字幕標籤同步顯示目前語言。
- 啟用本機 Avatar 時先呼叫受保護的 warm-up API，待 Breeze ASR、CosyVoice3 與
  MuseTalk 全部 loaded 才進入已啟用狀態，後續問答不再重複載入模型。
- Breeze ASR 回傳空文字或失敗時，保留失敗狀態並由已連線醫生說「對不起，我沒有
  聽清楚，請再講一次」，播放結束後重新開始語音輸入。
- Node regression tests、Vite build、OpenAPI drift 與 Chrome 互動驗證涵蓋語言選擇、
  warm-up、重試提示及桌面／手機版顯示。

### v1.4.0 (2026-08-10)

- 修正 Vite 開發模式找不到 `/avatar/doctor.png` 的問題，改由 frontend build
  帶入既有醫師圖片；本機 Avatar 啟用後在問診畫面上方顯示置中的醫師舞台，
  並在旁邊同步顯示目前朗讀字幕。
- Avatar 播放完畢後，文字題預設開啟語音輸入；實際偵測到使用者開始說話後，
  連續靜音 5 秒會停止錄音、呼叫 Breeze ASR，並準備自動送出。
- ASR 結果先回填下方輸入框並保留 3 秒編輯時間；使用者開始輸入即取消自動
  送出，也可手動停止錄音後自行確認與送出。未啟用 Avatar 時維持既有手動語音流程。
- Node tests、OpenAPI type drift、Vite production build，以及實際 Chrome 桌面／手機
  viewport 的 Avatar 圖片、字幕、輸入列與預設錄音流程驗證通過。

### v1.3.0 (2026-08-10)

- 開發版 frontend 的預設 API port 改為 `18000`，固定連到 integration Compose
  提供的 host-loopback Nginx gateway，避免與仍在 `8000` 的本機 Uvicorn 衝突。
- Frontend 繼續由 Vite hot reload；backend、病例資料庫、Breeze ASR 與 Avatar
  統一由 Docker Compose 提供。跨來源 credentials 既有的 fail-closed 行為不變。
- 更新 backend URL regression tests，並以 Node tests、production build 與 API type
  drift check 驗證。

### v1.2.0 (2026-08-09)

- Safety structured-rule editor 分別保存 `all_findings` 與 `any_findings`，切換 operator
  或無修改發布 round-trip 不再遺失另一組條件。
- 顯示兩組 finding 數量以及目前搜尋／分類 filter 隱藏的已選項目，可明示一次清除，
  避免看不到仍將發布的條件。
- Safety draft assistant 使用 AbortController 與 request sequence；切換群組、取消編輯
  或 component scope dispose 後，過期 response 不會回寫新草稿。
- 同步更新 API error contract types；13 項 Node tests、OpenAPI type drift 與 Vite
  production build 通過。Vue mount/browser interaction test 仍列於根 README 待辦。

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

前端預設使用目前網頁 hostname 與 port `18000` 連接 integration Compose 的
loopback Nginx gateway，再由 gateway 連接 Docker FastAPI。正式環境與預設設定
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
VITE_BACKEND_PORT=18000
# 正式同源 reverse proxy 可改用：
# VITE_BACKEND_BASE_URL=/api
```

啟動完整 Docker backend pipeline：

```bash
cd integration-deployment
docker compose up -d --build
```

發生「無法連線到後端」時，先開啟 `http://127.0.0.1:18000/v1/health` 確認
Docker gateway 可達，再檢查 frontend 的 backend URL 設定。Port 18000 僅綁在
同一台主機的 loopback，不提供手機或其他電腦直接存取。

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

啟用 Avatar 後，醫師影像與朗讀字幕會顯示在問診畫面上方。每次 Avatar 播放
完成後會自動開啟麥克風；使用者開始說話後連續停頓 5 秒，錄音會自動交給
Breeze ASR。辨識文字回填輸入框後有 3 秒可直接編輯，任何編輯都會取消自動
送出；按下麥克風手動停止的錄音則不會自動送出。Avatar 設定可選國語或閩南語；
若 ASR 沒有辨識出內容，醫生會以目前語言請使用者再說一次。

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
