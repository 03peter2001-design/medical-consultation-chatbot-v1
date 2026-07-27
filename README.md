# AI 預問診系統（Medical Consultation Chatbot）

AI 輔助預問診系統。使用者（病患端）用文字或語音回答一系列問題，系統會即時判斷主訴類型（胸痛／頭痛／腹痛），走對應的問診流程，最後透過 LLM（Groq 或 Gemini）產生一份結構化的 AI 初步評估報告；醫師端則可以用問診編號查詢病人資料、閱讀 AI 報告，並針對追加的補充資訊自動生成結構化病歷分析。

## 目前功能

- **病患端**（Vue 路由 `/#/`）：流程依序為「自由主訴 → 基本資料 → 一般病史 → 疾病問卷」；選擇題使用單選／複選並保留自由補充，出生日期使用日期選擇器，可點選正／背面人體圖標記多個疼痛位置，完成後產生 AI 初步評估報告與問診編號
- 使用身分證字號從 FHIR 載入病歷時，姓名、性別、出生日期與血型等既有基本資料不會重問；一般病史同樣只補問 FHIR 尚未提供的欄位。身分證字號本身不會送入 `/chat`、RAG 或外部模型
- FHIR `$everything` 中的 `Condition`、`Procedure`、`MedicationStatement`、`MedicationRequest`、`AllergyIntolerance` 與 `QuestionnaireResponse` 會映射到一般病史、心肺／神經／腹部疾病史、手術史、用藥與過敏欄位；本次就診的 `encounter-diagnosis` 不會誤當成既往病史
- **醫師端**（Vue 路由 `/#/doctor`）：輸入問診編號載入病人資料、同步查看病人標記的疼痛位置與 AI 報告、可另外輸入病人口語補充內容，系統會自動生成六段式結構化病歷分析
- **RAG（檢索增強生成）**：清理 `backend/docs/` 中急診醫學、感染科與檢驗醫學三份爬蟲語料，切成 chunks 後分類到胸痛、頭痛、腹痛、共通與安全五個 versioned Chroma collections。檢索會依主訴動態選庫、固定加入安全庫，必要時追加共通或另一個症狀庫，再以 RRF 合併及去重
- **雙語檢索（實驗功能）**：可保留中文原查詢，並以 Gemini 產生去識別化的結構化英文查詢，同時檢索相同 collections；翻譯失敗時會退回原本的多語 embedding 查詢
- 目前支援 3 種問診情境：**胸痛、頭痛、腹痛**。系統優先以明確關鍵字判斷自由主訴；主訴不明確或同時符合多類時才交由 LLM 分流，再載入對應問卷

## 專案結構

```
medical-consultation-chatbot-v1/
├── frontend/                # Vue 3 + Vite 前端
│   ├── src/
│   │   ├── components/      # 共用 UI 元件
│   │   ├── composables/     # D-ID Avatar 狀態與操作
│   │   ├── services/        # 後端 API 與連線設定
│   │   └── views/           # 病患端與醫師端頁面
│   ├── tests/               # 前端單元測試
│   └── package.json
├── index.html               # 舊版病患端（相容保留）
├── doctor.html              # 舊版醫師端（相容保留）
├── backend/
│   ├── main.py               # FastAPI 後端主程式（問診流程、LLM呼叫、API）
│   ├── questionnaires.py     # 分類問卷 JSON 的 lazy loader、快取與驗證
│   ├── questionnaire_data/   # 主訴、基本、病史及三種疾病問卷 JSON
│   ├── rag.py                 # RAG 檢索邏輯
│   ├── rag_translation.py     # Gemini 中英查詢正規化與去識別化
│   ├── clean_documents.py     # 清理三份爬蟲語料
│   ├── classify_chunks.py     # chunk 多標籤分類與人工審查清單
│   ├── ingest.py              # 建立向量資料庫用的腳本
│   ├── requirements.txt       # Python 套件需求
│   ├── docs/                  # RAG 知識庫來源文件（.txt）
│   ├── .env                   # 環境變數（需自行建立，不會上傳到 GitHub）
│   └── chroma_db/              # 向量資料庫（需自行執行 ingest.py 產生，不會上傳到 GitHub）
└── pic/                     # 圖片素材
```

> `.env` 和 `chroma_db/` 都被排除在版本控制之外（見 `.gitignore`），所以 clone 下來之後**必須自己重新建立**，步驟見下方。

## 安裝與啟動步驟

### 1. 下載專案

```bash
git clone git@github.com:03peter2001-design/medical-consultation-chatbot-v1.git
cd medical-consultation-chatbot-v1
```

### 2. 設定後端環境

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 建立 `.env`

先執行 `cp .env.example .env` 複製範例設定，再於 `backend/.env` 選擇 Groq 或 Gemini（二選一）。

使用 Gemini：

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=你的Gemini API Key
```

使用 Groq：

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=你的Groq API Key
```

Gemini Key 可至 [Google AI Studio](https://aistudio.google.com/app/apikey) 申請；Groq Key 可至 [Groq Console](https://console.groq.com/keys) 申請。

`LLM_PROVIDER` 若省略，系統會優先使用 `GROQ_API_KEY`，沒有 Groq Key 時再使用 `GEMINI_API_KEY`，因此既有設定不需要修改。模型也可用 `GEMINI_MODEL` 或 `GROQ_MODEL` 覆寫，預設分別為 `gemini-2.5-flash` 與 `llama-3.3-70b-versatile`。

若聊天模型使用 `gemini-2.5-pro`，後端會為不可關閉的 thinking 預留
128 tokens，並把可見回答額度另外加到 `max_output_tokens`；可用
`GEMINI_THINKING_BUDGET` 覆寫。若模型因 `MAX_TOKENS` 未產生正文，
系統會提高上限自動重試一次。

### 4. 建立向量資料庫（RAG）

`backend/docs/` 裡已經附上三份 Medscape 爬蟲資料。RAG v2 依序進行
清洗、chunk 多標籤分類、建庫 dry-run，再平行建立五個 collections：

```bash
python clean_documents.py
python classify_chunks.py
python ingest.py --version v2 --dry-run
python ingest.py --version v2
```

以目前語料執行後，清洗結果為 1,585 篇文章、40,526 個 chunks；其中符合
索引條件的內容會進入 `medical_v2_chest`、`medical_v2_headache`、
`medical_v2_abdomen`、`medical_v2_common` 與 `medical_v2_safety`，
其餘內容保留為 `archive`，不建立向量。實際數量以每次產生的
`classification_report.json` 與 dry-run 報告為準。

清洗產物位於 `backend/clean_docs/`，分類語料、統計與人工審查清單位於
`backend/classified_docs/`；分類階段產生的 embeddings 會由建庫直接重用，
不會對同一批 chunks 重算一次。新索引不會刪除原本的 `medical_kb`；驗證通過後，
在 `.env` 設定 `RAG_INDEX_VERSION=v2` 並重新啟動後端即可切換。移除此設定
或改成 `legacy` 可立即回退。

如需比較 v2 與舊索引的 45 題固定測試：

```bash
RAG_INDEX_VERSION=v2 python evaluate_rag.py --version v2 --compare-legacy --enforce
```

### Gemini 中英查詢正規化（實驗功能）

RAG 資料為英文、病人問診為中文時，可在去識別化測試環境開啟 Gemini
查詢正規化：

```dotenv
RAG_QUERY_TRANSLATION=gemini
RAG_QUERY_MODE=dual
GEMINI_API_KEY=你的Gemini_API_Key
```

`dual` 會保留中文原查詢，並以 Gemini 產生結構化英文檢索查詢；兩組
embeddings 會批次查詢相同 collections，再用 RRF 合併及去重。
`english` 只使用英文查詢，適合 A/B 實驗，但不是預設建議。

送往 Gemini 前會遮蔽常見身分證、電話、Email、病歷號、姓名及地址標籤；
Gemini 回傳必須符合固定 JSON Schema，任何 API、格式或內容驗證失敗都會
自動退回原本的多語 embedding 查詢。日誌只記錄是否使用翻譯、耗時與
查詢 variant，不記錄原文或翻譯內容。

此功能預設為 `off`。一般 Gemini Developer API 的服務條款與資料治理不應
直接視為符合臨床或個資規範；正式病人流程啟用前，仍須完成機構法務、
資安、資料保護與醫療審查。

### 5. 啟動後端

```bash
uvicorn main:app --reload
```

後端預設會跑在 `http://127.0.0.1:8000`。看到終端機顯示 `[RAG] 向量庫已載入，RAG 功能啟用` 代表 RAG 有正確載入。

### 6. 啟動 Vue 前端

另開一個終端機，在專案根目錄執行：

```bash
cd frontend
npm install
npm run dev
```

前端支援 Node.js 18 以上版本。Vite 預設會顯示本機開發網址
（通常是 `http://localhost:5173`）：

- `http://localhost:5173/#/` → 病患端（開始問診）
- `http://localhost:5173/#/doctor` → 醫師端（輸入問診編號查詢病人）

正式建置可執行 `npm run build`，輸出位於 `frontend/dist/`。根目錄的
`index.html` 與 `doctor.html` 是重構前的舊版，暫時保留供比對與相容使用。

### 7.（選用）連接測試用 HAPI FHIR Server

Vue 病患端可直接連接開發環境中的 HAPI FHIR Server。先複製前端設定：

```bash
cd frontend
cp .env.example .env
```

再設定：

```dotenv
VITE_ENABLE_DIRECT_FHIR=true
VITE_FHIR_BASE_URL=http://localhost:8080/fhir
```

前端會以台灣身分證 identifier system
`http://www.moi.gov.tw` 查詢 `Patient.identifier`，找到唯一病人後再讀取
`Patient/{id}/$everything`。HAPI Server 必須允許前端開發網址的 CORS。
可匯入的測試 FHIR Bundle 位於
`backend/fhir_samples/synthetic_chest_pain_case.json`。

身分證直接查詢只供本機或受控測試環境使用。正式環境不應讓瀏覽器直接
存取臨床 FHIR Server，應改由具備驗證、授權與稽核的院內後端代理處理。

### 8.（選用）設定 D-ID 虛擬數位人語音互動

病患端網頁左側有一個「D-ID 設定」欄位，需要輸入：
- **Client Key**：去 [studio.d-id.com](https://studio.d-id.com) 註冊後取得
- **Agent ID**：在 D-ID Studio 建立一個 Agent 後取得

不填這兩個欄位一樣可以用純文字/語音輸入方式問診，只是不會有虛擬數位人開口說話的效果。

## 測試用假病人（醫師端）

醫師端輸入問診編號 **`00000`** 可以直接載入一筆預先寫好的測試胸痛病人資料，方便開發/展示時不用每次都重新跑一次完整問診。這筆資料的 AI 初步評估是預先寫死的文字（並非即時呼叫模型產生），報告內文有清楚標註「測試用假病人資料」，不會被誤認為真實案例。

## 常見問題

**Q: 啟動後端時出現 `[RAG] 未找到 chroma_db，請先執行 python ingest.py`？**
A: 代表你還沒建立向量資料庫，回到步驟 4 依序執行清洗、分類及
`python ingest.py --version v2`。

**Q: 前端顯示無法連線到後端？**
A: 前端會自動使用目前網頁的 hostname，並以 `8000` 作為預設後端 port。請先在瀏覽器開啟 `http://後端主機:8000/health` 確認能看到健康狀態。

- 若後端使用其他 port，例如 `9000`，以 `http://localhost:5173/?backendPort=9000#/` 開啟。
- 若後端位於其他主機，以 `http://localhost:5173/?backend=http://192.168.1.20:9000#/` 開啟；切換到醫師端時設定會保留。
- 也可在 `frontend/.env` 設定 `VITE_BACKEND_PORT=9000` 作為該環境的預設 port。
- 若從手機或另一台電腦連線，後端需用 `uvicorn main:app --reload --host 0.0.0.0 --port 8000` 啟動，並確認防火牆允許該 port。

**Q: `.env` 或 `chroma_db` 不見了？**
A: 這是正常的，這兩個東西本來就不會被上傳到 GitHub（見 `.gitignore`），照步驟 3、4 自己重新建立即可。

## 開發規劃

- [x] 將前端重構為 Vue 3 + Vite
- [x] 將主訴、基本資料、一般病史與疾病問卷拆成獨立 JSON
- [x] 建立胸痛、頭痛、腹痛、共通與安全的 RAG v2 collections
- [x] 加入可選的 Gemini 中英 dual-query 檢索與失敗 fallback
- [ ] 完成 RAG 安全庫、低信心分類與黃金測試集的醫療專業審查
- [ ] 正式環境改用具備身分驗證、授權與稽核的 FHIR 後端代理
- [ ] 導入狀態感知的動態追問、候選疾病變化與可解釋問診停止條件
