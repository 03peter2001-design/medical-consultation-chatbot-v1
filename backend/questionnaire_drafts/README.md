# Provisional 問卷草稿

此目錄保存由 `docs/疾病問卷.txt` 經本機 RAG 與 Gemini 一次性結構化後的審查
草稿。`scripts/promote_questionnaires.py` 只有在完整 clinical signoff manifest
通過 reviewer、日期、問卷來源與 route catalog hash、逐路由核准與 blocking review-note 驗證後才會
提升；不可手動複製，以免繞過稽核、帶入 `source_lines` 或覆寫既有三痛 stable
contract。

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

目前 49 份結構化 candidate 可接受 schema、來源與前端 metadata drift 檢查，但
不會加入主訴分類或病患執行期。既有三痛仍是唯一核准路由，保留完整
ClinicalFact／疾病投票。心臟驟停、槍傷、中風、藥物過量、失去意識、性暴力等
候選類別的緊急／人工流程仍屬待簽核政策；在核准前一律由既有 Safety 或 unsupported
route 的 fail-closed handoff 保護，不執行 candidate 長問卷。

原始檔共有 52 個編號類別；其中胸痛、頭痛、腹部問題與現行三條路由重疊，
因此是 49 個非重疊的新類別。重疊類別只能合併審查，不可覆寫現行 stable field
與 Safety contract。
