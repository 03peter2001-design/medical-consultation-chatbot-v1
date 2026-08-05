# AI 預問診系統（Medical Consultation Chatbot）

AI 輔助預問診系統。病患可用文字或語音完成胸痛、頭痛或腹痛的結構化問診；
醫師可依問診編號查看原始回答、固定疾病表排名、摘要與臨床分析。

本專案目前是研究與合成資料開發原型，不是醫療器材，也不提供正式診斷。
疾病票數、完整度與排序均不代表患病機率，正式臨床使用仍需醫師審查、院方整合、
身分與權限管理、稽核及資料治理。

## 系統總覽

- **病患端**：自由主訴、FHIR 病歷預填、安全必問題、動態問卷與疼痛位置標記
- **確定性問診**：LLM 只抽取附有原文證據的 ClinicalFact；Safety、疾病票數、
  完整度、下一題與停止條件皆由本機規則執行
- **醫師端**：病例搜尋、醫師速覽、六段式分析、SNOMED CT 查詢與規則中心
- **本機資料層**：SQLite 保存問診結果，Chroma 保存版本化 RAG collections
- **FHIR／SMART**：支援 TW Core 開發環境、SNOMED CT 匯入及本機 SMART on FHIR
  合成病例流程
- **RAG**：僅供疾病表離線建置、醫師文獻問答及背景檢查／檢驗／影像建議；
  不參與病患端 Safety 或疾病投票

```text
病患端：病人原話 → LLM 抽取具原文證據的 ClinicalFact
                  → 本機 Safety／問卷／固定疾病表投票 → 問診結果

醫師端：中文問題 → 去識別化與醫療術語英文化
                → 本機 embedding／Chroma 檢索 → LLM 整理來源片段
```

## 快速開始

需求：Git、Bash、Python 3.12+、Node.js 18+；FHIR／SMART 流程另需 Docker 與
Docker Compose v2。Windows 建議使用 WSL2。

```bash
git clone git@github.com:03peter2001-design/medical-consultation-chatbot-v1.git
cd medical-consultation-chatbot-v1
./scripts/bootstrap.sh
```

第一次執行時，腳本會建立後端虛擬環境、安裝前後端依賴、建置 Vue frontend，
並準備本機 HAPI FHIR／TW Core（不需要 FHIR 時可加 `--skip-fhir`）。接著填妥
`backend/.env` 中的 Gemini 或 Groq API key。

需要建立完整 RAG 索引時執行：

```bash
./scripts/bootstrap.sh --with-rag
```

本機開發可分別啟動：

```bash
# Terminal 1
cd backend
source venv/bin/activate
uvicorn main:app --reload

# Terminal 2
cd frontend
npm run dev
```

預設入口：

- 病患端：`http://localhost:5173/#/`
- 醫師端：`http://localhost:5173/#/doctor`
- SNOMED CT：`http://localhost:5173/#/doctor/terminology/snomed`
- API 文件：`http://127.0.0.1:8000/docs`

完整的環境需求、建制選項與快取行為請見 [建制腳本說明](scripts/README.md)。

## 專案目錄

```text
.
├── backend/               FastAPI、AMIE、RAG、SQLite 與術語整合
├── frontend/              Vue 3 + Vite 病患端與醫師端
├── scripts/               一鍵建制與 SMART 啟動腳本
├── smart-app/             SMART launch 頁面與正式前端容器設定
├── smart-deployment/      SMART／FHIR 本機 proxy 設定
├── docs/                  OpenAPI、研究文件與工作規劃
├── devlog/                依日期整理的開發紀錄
├── pic/                   圖片素材
├── compose.fhir.yml       HAPI FHIR、PostgreSQL、TW Core、SNOMED services
└── compose.smart.yml      完整 SMART 開發環境
```

`index.html` 與 `doctor.html` 是 Vue 重構前的相容版本；目前開發入口位於
`frontend/`。`SMART-APP-Exercise-1/`、`package/` 為外部範例／套件資料，
不屬於主要應用程式碼。

## 文件索引

| 主題 | 文件 |
| --- | --- |
| 後端安裝、環境變數、API、資料庫、AMIE、規則中心與品質檢查 | [backend/README.md](backend/README.md) |
| Vue 路由、前端設定、FHIR 預填與 D-ID | [frontend/README.md](frontend/README.md) |
| RAG 語料清洗、分類、建庫、評估與雙語檢索 | [backend/knowledge/README.md](backend/knowledge/README.md) |
| RAG 原始語料的用途與不可變原則 | [backend/docs/README.md](backend/docs/README.md) |
| 問卷 JSON 格式與載入規則 | [backend/questionnaire_data/README.md](backend/questionnaire_data/README.md) |
| Safety 規則結構 | [backend/amie/rules/README.md](backend/amie/rules/README.md) |
| HAPI FHIR、TW Core 與 SNOMED CT | [backend/terminology/README.md](backend/terminology/README.md) |
| SMART on FHIR 本機整合流程 | [smart-app/README.md](smart-app/README.md) |
| SMART／FHIR proxy 設定 | [smart-deployment/README.md](smart-deployment/README.md) |
| 自動建制與啟動腳本 | [scripts/README.md](scripts/README.md) |
| OpenAPI、研究資料與開發規劃 | [docs/README.md](docs/README.md) |
| 正式 SMART 臨床應用構想 | [future.md](future.md) |

## 目前狀態

胸痛、頭痛、腹痛問卷、確定性疾病表投票、RAG v2、SMART OAuth launch context
與規則治理原型均已可運行。待辦重點是醫療專業審查、正式身分與權限整合、
FHIR 回寫治理，以及疾病表權重與 SNOMED CT coding 的醫師校準；詳見
[開發文件](docs/README.md)。
