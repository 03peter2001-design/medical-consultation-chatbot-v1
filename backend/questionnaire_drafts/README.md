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

## 疾病名稱導向的 AMIE clinical-artifact 草稿

`clinical_artifacts/v1/<run-id>/` 是另一條隔離 pipeline，不是上述 questionnaire-only
promotion 的輸入。它先以初始 route RAG 讓 Gemini 提出標準英文疾病名稱，再把每個
疾病名稱逐一用於第二階段 RAG query；最後每個疾病各自呼叫 Gemini，建立 proposed
ClinicalFact、exact-choice `semantic_options` overlay、疾病 profile 與 Safety 候選。

```bash
cd backend
venv/bin/python -m scripts.build_amie_route_drafts \
  --run-id 20260810-gemini-disease-rag-v8
```

可用重複 `--only <route>`、`--limit` 與 `--max-attempts 1..5` 分批續跑；互不重疊的
shard 必須加 `--no-manifest`，完成後再由單一 reducer 執行：

```bash
venv/bin/python -m scripts.build_amie_route_drafts \
  --run-id 20260810-gemini-disease-rag-v8 --reduce-only
```

每個 run 具有以下不可混淆的邊界：

- `discoveries/<route>.json`：第一階段疾病名稱、初始 RAG chunks、query 與 hashes。
- `routes/<route>.json`：第二階段疾病名 query、逐 chunk scope、facts、semantics、
  profiles、Safety candidates 與 review notes。
- `failures/<route>.json`：失敗嘗試；route 後續成功時仍保留研究稽核紀錄。
- `manifest.json`：49-route 完整性、artifact hashes、全域 code collision 檢查、總數與
  blocking summary。`complete` 只表示 49 份生成檔齊全，不代表臨床可用。

正式 v8 run 雖為 49/49 complete，仍固定標示 `runtime_eligible=false`、
`clinical_review_ready=false`、`citation_review_status=unverified`。它含 163 個疾病名稱
候選、118 個 profiles 與 82 個 Safety candidates，但仍有 45 個 profile 缺口、16 條
無 Safety 路徑、6 條 evidence insufficient 與 8 個 critical review notes。v1–v7 是
schema／prompt pilot 與失敗實驗；其結論記錄於 devlog，原始生成目錄不納入版本控制。

這些 JSON 故意與 active loaders 不相容，且 `lifecycle.executable=false`。不得手動複製
到 `questionnaire_data/`、`amie/disease_data/` 或 `amie/rules/safety_rules.json`；現有
`promote_questionnaires.py` 只審 questionnaire 結構，沒有能力核准這批 clinical
artifacts。未來若要上線，必須另建逐 route、跨 semantic／profile／Safety 的 composite
clinical signoff、gold cases 與 all-or-nothing publisher。
