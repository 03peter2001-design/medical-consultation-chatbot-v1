# 後端服務

`backend/` 是 FastAPI 應用、AMIE-inspired 確定性問診、SQLite repository、
RAG 查詢服務與 FHIR／SNOMED 整合所在位置。

## 目錄與責任

| 路徑 | 責任 |
| --- | --- |
| `main.py` | ASGI 入口，匯出 FastAPI `app` |
| `app/` | HTTP routes、request/response models、服務與 prompts |
| `domain/` | 問卷、疼痛位置與術語領域邏輯 |
| `infrastructure/` | LLM provider 與 SQLite repository |
| `amie/` | ClinicalFact、Safety、疾病表投票、選題與稽核流程 |
| `questionnaire_data/` | 主訴、基本資料、病史及三種疾病問卷 JSON |
| `knowledge/` | RAG 共用常數、檢索、taxonomy 與查詢翻譯 |
| `scripts/` | 清洗、分類、建庫、評估、OpenAPI 與術語 CLI |
| `terminology/` | TW Core packages、SNOMED CT installer 與本機索引 |
| `fhir_samples/` | 合成 FHIR 測試病例 |
| `tests/` | 後端單元與契約測試 |
| `data/` | 本機問診與稽核資料；由程式建立且不提交 Git |

RAG 流程請見 [knowledge/README.md](knowledge/README.md)，問卷格式請見
[questionnaire_data/README.md](questionnaire_data/README.md)，術語環境請見
[terminology/README.md](terminology/README.md)。

## 安裝

需求為 Python 3.12+。從本目錄建立虛擬環境並安裝 runtime dependencies：

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

專案根目錄的 `./scripts/bootstrap.sh` 可代為完成這些步驟；詳細選項請見
[../scripts/README.md](../scripts/README.md)。

## 環境變數

先複製範例：

```bash
cp .env.example .env
```

選擇 Gemini 或 Groq provider，並填入自己的 API key：

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=你的_Gemini_API_Key
INTERVIEW_ENGINE=amie
```

或：

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=你的_Groq_API_Key
INTERVIEW_ENGINE=amie
```

Gemini Key 可由 [Google AI Studio](https://aistudio.google.com/app/apikey) 申請，
Groq Key 可由 [Groq Console](https://console.groq.com/keys) 申請。

`LLM_PROVIDER` 省略時會優先使用 `GROQ_API_KEY`，沒有 Groq key 才使用
`GEMINI_API_KEY`。模型可用 `GEMINI_MODEL` 或 `GROQ_MODEL` 覆寫；預設分別為
`gemini-2.5-flash` 與 `llama-3.3-70b-versatile`。

常用設定：

| 變數 | 用途 |
| --- | --- |
| `INTERVIEW_ENGINE=amie` | 啟用 evidence-grounded ClinicalFact 與確定性問診 |
| `INTERVIEW_ENGINE=legacy` | A/B 比較或緊急回退至順序式問卷 |
| `AMIE_MAX_TURNS` | 動態問診輪數上限，預設 24 |
| `AMIE_DEBUG_TRACE=true` | 測試時顯示去除疾病票數與排名後的決策摘要 |
| `ASR_PROVIDER=breeze` | 使用本機 `MediaTek-Research/Breeze-ASR-26` 辨識錄音 |
| `BREEZE_ASR_DEVICE=auto` | 有 CUDA 時使用 GPU/FP16，否則使用 CPU/FP32 |
| `BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=true` | 每次 CUDA 辨識後卸載模型，讓同卡 Avatar 使用顯存 |
| `BREEZE_ASR_MODEL` | 覆寫 Hugging Face 模型 ID 或本機模型目錄 |
| `ASR_MAX_AUDIO_SECONDS` | 後端接受的單次錄音上限，預設 120 秒 |
| `ASR_MIN_AUDIO_RMS` | 靜音／過小音量門檻，預設 0.001，避免將靜音幻覺成病人回答 |
| `AVATAR_ENABLED=true` | 啟用私有網路上的本地 CosyVoice3 + MuseTalk 服務 |
| `AVATAR_SERVICE_URL` | Avatar 容器內網 URL；整合部署為 `http://avatar:8090` |
| `AVATAR_TIMEOUT_SECONDS` | 首次載入與影片生成逾時，整合部署預設 600 秒 |
| `ALLOW_LOCAL_AUTH_BYPASS=true` | 只在 loopback 開發時略過病患 session 與 UCC Bearer；預設關閉 |
| `CONSULTATION_DB_PATH` | SQLite 路徑；相對路徑以 `backend/` 為基準 |
| `SAFETY_RULE_ADMIN_TOKEN` | 啟用規則中心編輯；未設定時維持唯讀 |
| `FHIR_BASE_URL` | HAPI FHIR terminology server URL |
| `RAG_INDEX_VERSION=v2` | 使用 RAG v2 collections；移除或設為 `legacy` 可回退 |

若使用 `gemini-2.5-pro`，後端會為不可關閉的 thinking 預留 128 tokens，並將
可見回答額度另外加入 `max_output_tokens`；可用 `GEMINI_THINKING_BUDGET`
覆寫。模型因 `MAX_TOKENS` 沒有產生正文時，系統會提高上限重試一次。

`.env` 含有祕密，不得提交版本控制。

本機直接以 `http://127.0.0.1:5173` 開發舊版 `frontend/` 時，可在
`backend/.env` 設定 `ALLOW_LOCAL_AUTH_BYPASS=true`。後端只會對
`127.0.0.0/8` 或 `::1` 的直接連線略過病患 session 與 UCC Bearer；
判斷依據是無法由用戶偽造的 TCP peer IP，不是 `Host` header。非 loopback
來源、integration deployment 與正式環境仍強制完整驗證。本機舊版
`frontend/` 的開發身分不套用院所篩選，因此可讀取尚未寫入
`institution_id` 的舊病例；正式 Bearer 身分仍依院所隔離。

### Breeze 語音辨識

語音端點預設改用本機 Breeze-ASR-26，不再將病人錄音傳給
Gemini 或 Groq。系統需要 `ffmpeg`；Ubuntu/WSL 可先安裝：

```bash
sudo apt-get install ffmpeg
```

模型採延遲載入，第一次辨識會從 Hugging Face 下載約 6 GB 權重並
花較長時間。之後同一後端 process 會重用模型。本專案的 RTX 5060 Ti /
CUDA 12.8 開發機可安裝與參考專案相同的 wheel：

```bash
cd backend
venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cu128 \
  torch==2.11.0
```

`BREEZE_ASR_DEVICE=auto` 會自動選擇 GPU/FP16，否則回退 CPU/FP32；
部署機已確定有 GPU 時建議設為 `cuda`，未正確傳入 GPU 時會明確失敗，
避免不小心用 CPU 推論。同一張 16 GB GPU 還要執行 Avatar 時，整合部署會設
`BREEZE_ASR_RELEASE_GPU_AFTER_TRANSCRIBE=true`，在 inference lock 內完成辨識後
卸載 pipeline 並清除 CUDA cache；下一段錄音因此需要重新載入模型。CPU 模式不
受此設定影響。需要回退原有雲端辨識時設為 `ASR_PROVIDER=llm`。

瀏覽器端最長錄音 60 秒，辨識結果只會回填輸入框；病人需先確認或
修正文字才會送出問診答案。

### 本地語音與 Avatar

整合部署會以 `Fun-CosyVoice3-0.5B-2512` 合成 AI 回覆，再由 MuseTalk 1.5
依指定醫師圖產生唇形 MP4。模型服務沒有發布 host port；`/v1/avatar/status`
與 `/v1/avatar/speak` 都沿用病患 session 驗證。完整安裝、聲線替換與 GPU
調校說明見 [../avatar-service/README.md](../avatar-service/README.md)。

## 啟動與 API

```bash
uvicorn main:app --reload
```

後端預設位於 `http://127.0.0.1:8000`。正式 API 使用 `/v1` 前綴：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- 即時規格：`http://127.0.0.1:8000/openapi.json`
- 版本控制規格：`../docs/openapi.json`

修改 API model 或 route 後，更新 OpenAPI 與前端型別：

```bash
# backend/
python -m scripts.export_openapi
python -m scripts.export_openapi --check

# frontend/
cd ../frontend
npm run api:types
npm run api:check
```

產物 `frontend/src/generated/api.d.ts` 不應手動編輯。未加版本的舊路徑僅為
相容別名，不列入 OpenAPI；新程式一律使用 `/v1`。

## 問診與資料邊界

目前支援胸痛、頭痛與腹痛。自由主訴會先抽取附有逐字 evidence 的候選；
抽取失敗或仍不明確時，才退回既有 LLM 分科，再載入對應問卷。

病患原話先經確定性 Safety：

- 明確警訊不呼叫模型，直接終止並保存規則、鑑別方向與原始證據
- 未命中時，LLM 只能輸出白名單 ClinicalFact，且每項 evidence 都由程式驗證
- 三種主訴皆由程式執行支持票、反對票、完整度、穩定排序與下一題選擇
- urgent 核發三位數編號；routine 完成時核發五位數編號
- RAG 不參與病患疾病候選、Safety、票數或下一題

每輪會保存題目、回答、ClinicalFact、Safety 結果、投票快照、下一題、動態
疾病領先群、目標標籤、漏斗階段與確定性選題分數，並標記為
`deterministic_disease_vote`。這是可供稽核的決策摘要，不是模型隱藏思維鏈。

`amie/disease_data/{chest,headache,abdomen}.json` 是一次性 RAG＋離線 LLM
建表後提交版本控制的凍結產物，包含來源、corpus SHA-256、模型、不能漏診標記
及整數權重。目前是 `provisional`，不是患病機率或正式診斷。

fact 白名單、舊病例映射與 Safety 規則位於
`amie/rules/safety_rules.json`；必要欄位、選題策略、領先群票距與數量、停止門檻
及輪數上限位於 `questionnaire_data/*.json`。這裡的 AMIE 是依公開研究方法實作的流程，不是
Google 官方 AMIE 模型或服務，也不包含 self-play 訓練。

## FHIR 病歷預填

使用身分證字號由 FHIR 載入病歷時，姓名、性別、出生日期、血型及既有病史
不會重問；身分證字號不會送入 `/chat`、RAG 或外部模型。

`Patient/$everything` 中的 `Condition`、`Procedure`、`MedicationStatement`、
`MedicationRequest`、`AllergyIntolerance` 與 `QuestionnaireResponse` 會映射至
一般病史、分系統疾病史、手術史、用藥與過敏。本次就診的
`encounter-diagnosis` 不會被當成既往病史。

本機 FHIR／TW Core／SNOMED 環境請見
[terminology/README.md](terminology/README.md)，SMART OAuth 整合請見
[../smart-app/README.md](../smart-app/README.md)。

## 問診資料庫與測試病例

問診結果預設保存於 `data/consultations.db`，啟動時自動建立，不需 migration。
routine 與 urgent 都會先寫入結構化問卷、ClinicalFact、評分快照與分流結果，
立即核發編號；HTTP 回應送出後才在背景產生摘要與六段式臨床分析。

醫師速覽中的 Gemini 只負責壓縮既有病史；可能疾病與理由只來自固定疾病表及
病人的原始支持線索，不允許模型自行增加疾病。

摘要失敗不會讓病人失去編號；醫師端會顯示 `summary_pending`、
`summary_partial` 或 `summary_failed`。資料庫含病人資料，不應提交、公開或放置
於未加密位置；正式環境仍需備份、身分驗證、授權與稽核政策。

醫師端輸入問診編號 `00000` 可載入預先建立的胸痛假病人。其初步評估是固定
測試文字，並有「測試用假病人資料」標示，不會被誤認為真實病例。

## 醫師端規則中心

規則中心可查看實際執行中的全局流程、三種疾病表版本、問卷停止政策、Safety
規則、觸發條件與鑑別標籤。Safety 的唯一來源是
`amie/rules/safety_rules.json`，不散落於 Python 程式。

預設為唯讀。設定高強度 `SAFETY_RULE_ADMIN_TOKEN` 並重新啟動後端後，醫師
才可驗證權杖並使用編輯功能：

- Safety 規則可依分類搜尋與選取，或由微調助理產生最多五個標籤的草稿
- LLM 不得新增／刪除 rule code，也不能直接儲存；草稿需通過完整 JSON 驗證
- 正式發布需要變更理由、指定確認文字、相同管理權杖及版本衝突檢查
- 舊版先寫入 `data/safety_rule_audit/`，再以原子方式更新

疾病治理只允許調整既有疾病的白名單 ClinicalFact、存在／不存在方向及 1–10
整數權重，不能新增或刪除疾病。每個 `must_not_miss` 疾病至少需綁定一組穩定
`safety_rule_codes`；只有明確綁定的緊急觸發器會標記 urgent。

進階 fact label 設定使用完整白名單；標為 Safety 的單一 fact 以 `present` 命中
時會直接標記 urgent。需要多條件、特定原文或 FHIR 風險才成立的規則則保留在
「組合與原文 Safety 規則」。fact label 透過獨立的
`PUT /doctor/rules/fact-labels` 發布；兩種流程都執行版本衝突、確認文字與稽核。

既有疾病可新增或移除白名單標籤並調整方向、權重；新標籤沿用該疾病既有來源
集合，臨床依據由發布醫師負責。穩定 rule code 不可更名或刪除。

發布疾病表時需提供審查醫師、變更理由與指定確認文字。後端會驗證疾病與線索
集合、處理版本衝突、標記 `reviewed`、產生新 `profile_version`，並把差異與舊版
保存至 `data/disease_profile_audit/`。目前的權杖只適合原型；正式部署必須改用
具醫師身分驗證、角色授權與集中稽核的管理服務。

## 開發品質檢查

```bash
pip install -r requirements-dev.txt

ruff check .
ruff format --check .
pyright --project pyproject.toml
lint-imports --config .importlinter
coverage run -m unittest discover -s tests
coverage report
vulture
pip-audit -r requirements.txt
```

在 repository 根目錄執行 `pre-commit install` 後，每次 commit 前會執行 Ruff、
Pyright 與分層架構檢查；也可手動執行：

```bash
pre-commit run --all-files
```

## 疑難排解

### 啟動時顯示 `[RAG] 未找到 chroma_db`

尚未建立本機索引。依 [RAG 文件](knowledge/README.md) 執行清洗、分類與 ingest，
或在專案根目錄執行 `./scripts/bootstrap.sh --with-rag`。

### `.env` 或資料庫不存在

`.env`、`data/`、`chroma_db/`、`clean_docs/` 與 `classified_docs/` 都是本機設定
或衍生資料，不會由 Git 還原。複製 `.env.example`，並依各子系統文件重建所需
資料即可。
