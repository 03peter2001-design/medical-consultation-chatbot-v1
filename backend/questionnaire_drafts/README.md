# Provisional 問卷草稿

此目錄保存由 `docs/疾病問卷.txt` 經本機 RAG 與 Gemini 一次性結構化後的審查
草稿。它們不是執行期問卷，也不可直接複製到 `questionnaire_data/`。

產生完整草稿：

```bash
cd backend
venv/bin/python -m scripts.structure_questionnaires
```

產物位於 `v1/`：

- `01.json` 至 `52.json`：逐類別 provisional 草稿
- `manifest.json`：來源 SHA-256、模型、完整性與全域 ID 清單
- 每題 `source_lines`：原始非空白行的逐字、等序追溯
- `rag_sources`：本機 RAG chunk、距離、截斷 excerpt 與來源資訊
- `review_notes`：Gemini 依 RAG 產生、尚未人工核實的建議

發布前至少需要醫療、安全、隱私及 UX 審查，並補齊路由、確定性 Safety、
ClinicalFact、語意選項、報表與前端支援。特別是心臟驟停、槍傷、中風、藥物
過量、失去意識、性暴力等類別，必須先走核准的緊急／人工流程，不可讓一般
問卷延誤處置。

原始檔共有 52 個編號類別；其中胸痛、頭痛、腹部問題與現行三條路由重疊，
因此是 49 個非重疊的新類別。重疊類別只能合併審查，不可覆寫現行 stable field
與 Safety contract。
