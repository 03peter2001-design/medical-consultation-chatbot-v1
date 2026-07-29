# AI 預問診系統（Medical Consultation Chatbot）

AI 輔助預問診系統。使用者（病患端）用文字或語音回答一系列問題，系統會即時判斷主訴類型（胸痛／頭痛／腹痛），走對應的問診流程。胸痛鑑別使用版本化固定疾病表投票；LLM 只抽取有逐字證據的臨床線索，不產生疾病或分數。醫師端可以用問診編號查詢病人資料、閱讀固定排名與摘要，並針對追加資訊產生結構化病歷分析。

## 目前功能

- **病患端**（Vue 路由 `/#/`）：先收集自由主訴與尚未匯入的基本資料；胸痛依安全必問題與疾病表區辨力選題，頭痛／腹痛依核准問卷固定順序追問。選擇題支援單選／複選與自由補充，也可點選正／背面人體圖標記疼痛位置
- **狀態感知問診**：自由主訴先經原文確定性 Safety；明確警訊不呼叫模型、直接終止，醫師端會以 Safety JSON 的 `possible_conditions` 顯示安全規則觸發的鑑別方向與原始證據，不將其偽裝成疾病票數。未命中時 LLM 只能輸出白名單臨床事實，每項都必須附原文逐字 evidence 並通過程式驗證。Safety 仍獨立且優先；胸痛由程式執行「支持票－反對票」、完整度與穩定排序，執行期不查 RAG，也不讓 LLM 產生疾病、分數或下一題。urgent 核發三位數編號，routine 完成時核發五位數編號
- **版本化胸痛疾病表**：`backend/amie/disease_data/chest.json` 是一次性 RAG＋離線 LLM 建表後提交版本控制的凍結產物，包含來源、corpus SHA-256、模型、不能漏診標記與整數權重。目前標記為 `provisional`，票數及完整度都不是患病機率或正式診斷
- **JSON 規則驅動**：fact 白名單、scalar／舊病例映射及必要不能漏診疾病均位於 `backend/amie/rules/safety_rules.json`；必要欄位、選題策略、安全題順序、完整度門檻與輪數上限位於各路由的 `backend/questionnaire_data/*.json`。Python 只驗證設定並執行固定公式
- 使用身分證字號從 FHIR 載入病歷時，姓名、性別、出生日期與血型等既有基本資料不會重問；一般病史同樣只補問 FHIR 尚未提供的欄位。身分證字號本身不會送入 `/chat`、RAG 或外部模型
- FHIR `$everything` 中的 `Condition`、`Procedure`、`MedicationStatement`、`MedicationRequest`、`AllergyIntolerance` 與 `QuestionnaireResponse` 會映射到一般病史、心肺／神經／腹部疾病史、手術史、用藥與過敏欄位；本次就診的 `encounter-diagnosis` 不會誤當成既往病史
- **醫師端**（Vue 路由 `/#/doctor`）：左側病例資料庫可瀏覽、分頁及依姓名／問診編號／主訴搜尋，點選後同步查看疼痛位置與 AI 報告，並可經二次確認永久刪除病例
- **問診結果資料庫**：routine 與 urgent 都會先將結構化問卷、ClinicalFact、評分快照及分流結果寫入 SQLite、立即核發五位數或三位數編號；HTTP 回應送出後才在背景執行摘要及六段式臨床分析。摘要失敗不會讓病人失去編號，醫師端可辨識 `summary_pending`／`summary_partial`／`summary_failed`
- **測試期 AMIE 稽核軌跡**：每輪保存題目、病人回答、ClinicalFact、Safety 結果、投票快照、下一題、選題區辨分與簡短稽核理由，並標記為 `deterministic_disease_vote`。這是可供稽核的決策摘要，不是模型隱藏思維鏈
- **RAG（檢索增強生成）**：清理 `backend/docs/` 中急診醫學、感染科與檢驗醫學語料並建立 versioned Chroma collections。RAG 只供一次性疾病表建置、背景理學檢查／檢驗／影像建議，以及醫師主動聊天使用；不得參與病患疾病候選或票數計算
- **雙語檢索（實驗功能）**：可保留中文原查詢，並以 Gemini 產生去識別化的結構化英文查詢，同時檢索相同 collections；翻譯失敗時會退回原本的多語 embedding 查詢
- 目前支援 3 種問診情境：**胸痛、頭痛、腹痛**。主訴抽取器會同時提出有原文證據的分科候選；若抽取失敗或仍不明確，才退回既有 LLM 分科，再載入對應問卷

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
├── compose.fhir.yml         # HAPI FHIR、PostgreSQL 與 TW Core 自動安裝
├── backend/
│   ├── main.py               # FastAPI ASGI 入口（匯出 app）
│   ├── app/                  # HTTP 應用層
│   │   ├── factory.py        # FastAPI app factory 與 router 組裝
│   │   ├── runtime.py        # LLM、SQLite、RAG 與 session 資源
│   │   ├── models.py         # HTTP request schemas
│   │   ├── routes/           # 病患、醫師與系統 API
│   │   ├── services/         # 驗證、摘要、RAG、稽核與背景工作
│   │   └── prompts/          # 醫師端及病患摘要 prompts
│   ├── domain/               # 問卷、疼痛位置與術語領域邏輯
│   ├── infrastructure/       # LLM provider 與 SQLite repository
│   ├── knowledge/            # RAG 檢索、共用常數與翻譯
│   ├── scripts/              # 語料清理、分類、建庫與評估 CLI
│   ├── data/                  # 本機問診資料庫（自動建立，不上傳 Git）
│   ├── amie/                  # LangGraph、ClinicalFact、固定疾病表與安全規則
│   │   ├── chief_complaint.py # 主訴語意抽取、evidence驗證與FHIR風險輪廓
│   │   ├── disease_profiles.py # 疾病表驗證、確定性投票及選題區辨力
│   │   └── disease_data/      # 版本化、凍結的胸痛疾病表
│   ├── questionnaire_data/   # 主訴、基本、病史及三種疾病問卷 JSON
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

### 自動建制（建議）

執行前請先安裝以下系統層依賴；專案腳本會安裝 Python 與 npm 套件，但不會
用 `sudo` 修改作業系統：

| 工具 | 需求 | 安裝說明 |
| --- | --- | --- |
| Git、Bash | 可執行 `.sh` | [Git 官方下載](https://git-scm.com/downloads) |
| Python | 3.12+，且包含 `venv` | [Python 官方下載](https://www.python.org/downloads/) |
| Node.js、npm | Node.js 18+，建議使用 LTS | [Node.js 官方下載](https://nodejs.org/en/download) |
| Docker | Docker Engine 或 Docker Desktop | [Docker Engine 安裝](https://docs.docker.com/engine/install/) |
| Docker Compose | 支援 `docker compose` 的 v2 plugin | [Compose 安裝](https://docs.docker.com/compose/install/) |

Ubuntu／Debian 可先安裝基本工具；Python 3.12 與 Node.js 是否由系統 repository
提供，取決於發行版版本，缺少時請使用上表的官方安裝方式：

```bash
sudo apt update
sudo apt install -y git bash python3-venv
```

執行建制前可先確認：

```bash
git --version
python3 --version          # 必須是 3.12+
node --version             # 必須是 18+
npm --version
docker --version
docker compose version
docker info                # 確認目前使用者有權存取 Docker daemon
```

Windows 建議在 WSL2 中執行 Shell 腳本，並啟用 Docker Desktop 的 WSL
integration。macOS 可使用 Docker Desktop。確認上述指令成功後，在專案根目錄
執行：

```bash
./scripts/bootstrap.sh
```

Shell 腳本會先尋找 Python 3.12+ 並建立 `backend/venv`，再自動安裝或更新
Python dependencies、安裝 npm dependencies、建置 Vue frontend、啟動
HAPI/PostgreSQL，並安裝 TW Core。再次執行時會根據來源雜湊、輸出檔、
container 狀態與 HAPI 資料庫內的 terminology lock 標記跳過未變更步驟。

若系統的 Python 指令不是 `python3.12` 或 `python3`，可指定：

```bash
PYTHON_BIN=/path/to/python3.12 ./scripts/bootstrap.sh
```

如果 `backend/.env` 尚未存在，腳本會從 `.env.example` 建立；完成後仍須填入
自己的 Gemini 或 Groq API key。常用選項：

```bash
# 包含耗時的 RAG v2 清理、分類與建庫
./scripts/bootstrap.sh --with-rag

# 忽略快取狀態，重跑所有選定步驟
./scripts/bootstrap.sh --force

# 只準備後端與前端，不處理 FHIR
./scripts/bootstrap.sh --skip-fhir
```

也可使用 `--skip-backend` 或 `--skip-frontend`。建制狀態只保存在被 Git
忽略的 `.build-state/`；FHIR package 狀態則跟 PostgreSQL volume 一起保存，
因此移除資料庫後會正確重新安裝，不會被本機建制快取誤判。

以下章節保留各步驟的手動操作方式。

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
INTERVIEW_ENGINE=amie
```

問診結果預設儲存在 `backend/data/consultations.db`。如需改變位置，可設定
`CONSULTATION_DB_PATH`（相對路徑會以 `backend/` 為基準）：

```dotenv
CONSULTATION_DB_PATH=data/consultations.db
```

資料庫會在後端啟動時自動建立，無須另跑 migration。檔案包含病人問診資料，
請勿提交版本控制或放在公開目錄；正式環境仍應搭配磁碟加密、備份、身分驗證、
授權與稽核政策。

使用 Groq：

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=你的Groq API Key
```

Gemini Key 可至 [Google AI Studio](https://aistudio.google.com/app/apikey) 申請；Groq Key 可至 [Groq Console](https://console.groq.com/keys) 申請。

`LLM_PROVIDER` 若省略，系統會優先使用 `GROQ_API_KEY`，沒有 Groq Key 時再使用 `GEMINI_API_KEY`，因此既有設定不需要修改。模型也可用 `GEMINI_MODEL` 或 `GROQ_MODEL` 覆寫，預設分別為 `gemini-2.5-flash` 與 `llama-3.3-70b-versatile`。

`INTERVIEW_ENGINE=amie` 啟用 evidence-grounded 語意抽取與確定性問診；
若需要 A/B 比較或緊急回退，可改成 `INTERVIEW_ENGINE=legacy` 使用原本的
順序式問卷。可用 `AMIE_MAX_TURNS` 設定動態問診輪數上限（預設 24）。
測試期 `AMIE_DEBUG_TRACE=true` 會在病患端顯示去除疾病票數與排名後的
流程結果；醫師端仍會保留完整稽核軌跡。

這裡的 AMIE 是依公開研究方法實作的流程，不是 Google 官方 AMIE
模型或服務。第一版不包含 self-play 訓練，也不產生數字診斷機率。

若聊天模型使用 `gemini-2.5-pro`，後端會為不可關閉的 thinking 預留
128 tokens，並把可見回答額度另外加到 `max_output_tokens`；可用
`GEMINI_THINKING_BUDGET` 覆寫。若模型因 `MAX_TOKENS` 未產生正文，
系統會提高上限自動重試一次。

### 4. 建立向量資料庫（RAG）

`backend/docs/` 裡已經附上三份 Medscape 爬蟲資料。RAG v2 依序進行
清洗、chunk 多標籤分類、建庫 dry-run，再平行建立五個 collections：

```bash
python -m scripts.clean_documents
python -m scripts.classify_chunks
python -m scripts.ingest --version v2 --dry-run
python -m scripts.ingest --version v2
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
RAG_INDEX_VERSION=v2 python -m scripts.evaluate_rag --version v2 --compare-legacy --enforce
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

### 7.（選用）啟動含 TW Core 的 HAPI FHIR Server

專案已包含 HAPI FHIR 8.8.0、PostgreSQL 16 與 TW Core 自動安裝所需的
Compose 設定。從新的 clone 在專案根目錄執行：

```bash
docker compose -f compose.fhir.yml --profile setup up -d
```

第一次啟動會建立 PostgreSQL schema，接著 `twcore-installer` 會依鎖定順序
安裝專案內附的 9 個 FHIR NPM packages。這些檔案包含 TW Core 1.0.0 的
所有直接及傳遞依賴，安裝時不必另外下載 FHIR packages。可用以下指令確認：

```bash
docker compose -f compose.fhir.yml logs twcore-installer
```

看到 `Installed 9 locked FHIR packages` 即完成。首次建立 terminology index
可能需要數分鐘；`twcore-installer` 完成後正常狀態是結束碼 0，而 HAPI 與
PostgreSQL 會繼續執行。資料保存在 Compose volume，正常停止不會消失：

這個流程只需要此 repository 與 Docker；Docker 仍須從 registry 拉取已鎖定
版本的 HAPI、PostgreSQL 與 Python images。基於授權與發行範圍，完整
SNOMED CT 與 LOINC 資料不包含在 TW Core 依賴中，必須另行合法取得。

```bash
docker compose -f compose.fhir.yml down
```

`setup` profile 的用途是避免日後一般 `docker compose up -d` 重複安裝及
重建相同索引；installer 也會比對 HAPI 資料庫內的 lock SHA-256，相符時直接
跳過。如需對既有資料庫強制重新安裝鎖定套件，可執行：

```bash
docker compose -f compose.fhir.yml --profile setup run --rm twcore-installer \
  python -m scripts.install_twcore --server http://hapi:8080/fhir --force
```

HAPI 預設只綁定本機 `127.0.0.1:8080`。若 8080 已被占用，可在啟動時指定
其他連接埠，例如
`FHIR_PORT=18080 docker compose -f compose.fhir.yml --profile setup up -d`。
Compose 內的資料庫密碼只供本機開發，不可直接用於正式環境。

Vue 病患端可直接連接這台開發用 HAPI Server。先複製前端設定：

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

若未使用本專案的 Compose，也可對其他已啟用 runtime IG upload 的 HAPI
執行 `cd backend && python -m scripts.install_twcore`。套件清單、來源、
授權標示與 SHA-256 位於 `backend/terminology/packages.lock.json`。

身分證直接查詢只供本機或受控測試環境使用。正式環境不應讓瀏覽器直接
存取臨床 FHIR Server，應改由具備驗證、授權與稽核的院內後端代理處理。

### 8.（選用）設定 D-ID 虛擬數位人語音互動

病患端網頁左側有一個「D-ID 設定」欄位，需要輸入：
- **Client Key**：去 [studio.d-id.com](https://studio.d-id.com) 註冊後取得
- **Agent ID**：在 D-ID Studio 建立一個 Agent 後取得

不填這兩個欄位一樣可以用純文字/語音輸入方式問診，只是不會有虛擬數位人開口說話的效果。

## 後端開發檢查

開發環境改用額外的 requirements 安裝 Ruff、Pyright、Coverage、Vulture、
Import Linter、pip-audit 與 pre-commit；正式部署仍只需安裝
`requirements.txt`：

```bash
cd backend
pip install -r requirements-dev.txt
```

常用指令：

```bash
# import 排序、未使用名稱與常見語法錯誤
ruff check .
ruff check . --fix

# 檢查格式；需要套用格式時移除 --check
ruff format --check .

# 型別與模組引用
pyright --project pyproject.toml

# 分層架構
lint-imports --config .importlinter

# 測試與分支覆蓋率
coverage run -m unittest discover -s tests
coverage report

# 重構後的高可信度死碼
vulture

# requirements 中的已知套件漏洞
pip-audit -r requirements.txt
```

在專案根目錄執行一次 `pre-commit install`，之後每次 commit 前會自動檢查
Ruff、Pyright 與分層架構。也可手動執行全部 hooks：

```bash
pre-commit run --all-files
```

## 測試用假病人（醫師端）

醫師端輸入問診編號 **`00000`** 可以直接載入一筆預先寫好的測試胸痛病人資料，方便開發/展示時不用每次都重新跑一次完整問診。這筆資料的 AI 初步評估是預先寫死的文字（並非即時呼叫模型產生），報告內文有清楚標註「測試用假病人資料」，不會被誤認為真實案例。

## 常見問題

**Q: 啟動後端時出現 `[RAG] 未找到 chroma_db`？**
A: 代表你還沒建立向量資料庫，回到步驟 4 依序執行清洗、分類及
`python -m scripts.ingest --version v2`。

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
- [x] 導入 ClinicalFact 白名單、版本化胸痛疾病表與確定性投票
- [x] 加入安全題優先、投票區辨力選題、70% 停止條件與 24 輪轉交
- [ ] 由醫師審查並校準胸痛疾病表權重與 SNOMED CT Coding
- [ ] 建立經醫師審查的 self-play 資料與 MedGemma 微調流程
