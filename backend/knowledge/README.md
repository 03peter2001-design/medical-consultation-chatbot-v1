# RAG 知識庫

本目錄包含檢索共用常數、chunk 規則、Chroma 查詢與可選的 Gemini 中英查詢
正規化。語料處理 CLI 位於相鄰的 `scripts/`。

## 使用邊界

RAG 只用於：

- 一次性產生並人工審查版本化疾病表
- 醫師端主動文獻問答
- 背景理學檢查、檢驗及影像建議
- 六段式臨床分析的來源輔助

病患端 AMIE 執行時不查 RAG。RAG 不得產生或改變 Safety 結果、疾病候選、
支持／反對票、完整度與下一題。

## 資料目錄

| 路徑 | 性質 |
| --- | --- |
| [`../docs/*.txt`](../docs/README.md) | Medscape 爬蟲原始檔，永遠不原地修改 |
| `../clean_docs/` | 清洗後 JSONL 與清洗報告，本機衍生資料 |
| `../classified_docs/` | chunks、embeddings、分類報告及人工審查清單 |
| `../chroma_db/` | 本機 versioned Chroma collections |
| `taxonomy.json` | 路由、臨床階段與 Safety 分類詞彙 |

`docs/` 是來源，不是清洗結果。清洗器會保留原始三份 `.txt` 供稽核與重建，
並將結果寫至 `clean_docs/medical_articles.jsonl`。這些產物及 Chroma 都被 Git
忽略，clone 後需要自行重建。

目前的清洗是格式與固定網站標記清理，不是語意修復：它會正規化換行與空白、
移除控制／replacement characters、引用編號、少數導覽 marker 及相鄰重複行；
不會猜測原始爬蟲中已遺失的字母，也不會自動判斷所有圖片、表格或站內推薦文字。
清洗後文章以 `\n\n` 保留段落，但分類時 `chunk_text` 會將空白正規化為單一空格。

## 建置流程

在 `backend/` 執行：

```bash
python -m scripts.clean_documents
python -m scripts.classify_chunks
python -m scripts.ingest --version v2 --dry-run
python -m scripts.ingest --version v2
```

流程依序為：

```text
docs/*.txt
  → clean_docs/medical_articles.jsonl
  → classified_docs/classified_chunks.jsonl + classified_embeddings.f32
  → medical_v2_{chest,headache,abdomen,common,safety}
```

目前基準語料為 1,585 篇文章、40,526 個 chunks。符合索引條件者會寫入五個
collections，其餘保留為 `archive` 而不建立向量。實際數量以
`cleaning_report.json`、`classification_report.json` 與 ingest dry-run 為準。

六段式報告使用同一批 v2 route collections 上的三個 metadata 分區，而不是讓模型
自行決定要查哪一庫：

| 知識庫 | Chroma `clinical_stage` filter | 用途 |
| --- | --- | --- |
| A | `diagnosis`、`workup` | 初步鑑別、防漏診與理學檢查 |
| B | `lab` | 抽血與驗尿 |
| C | `imaging` | X-ray、超音波、CT、MRI 等影像決策 |

Backend 先以 filter 直接檢索對應分區，再把取回的 `retrieved_evidence` 傳入該題模型
request；prompt 不負責搜尋或選庫。這項分區只支援含 `clinical_stage` metadata 的 v2
索引，legacy 索引會 fail closed，不能作為 A／B／C 報告的靜默 fallback。

分類階段產生的 embeddings 會直接由 ingest 重用，不對相同 chunks 重算。
新索引不會刪除 legacy `medical_kb`；只有明確使用 `--rebuild` 才會重建相同
version 的目標 collections。

也可從 repository 根目錄一次完成：

```bash
./scripts/bootstrap.sh --with-rag
```

啟用新版索引：

```dotenv
RAG_INDEX_VERSION=v2
```

移除該變數或改成 `legacy` 可立即回退。啟動後端後，health／log 顯示 RAG
enabled 才代表作用中的 collections 與 embedding model 已完整載入。

## 評估

比較 v2 與 legacy 索引的固定測試：

```bash
RAG_INDEX_VERSION=v2 \
  python -m scripts.evaluate_rag --version v2 --compare-legacy --enforce
```

低信心與多路由內容會列入 `classified_docs/review_queue.csv`，正式採用前仍需
醫療專業審查。

## Gemini 中英查詢正規化（實驗功能）

英文語料搭配中文問題時，可在去識別化測試環境設定：

```dotenv
RAG_QUERY_TRANSLATION=gemini
RAG_QUERY_MODE=dual
GEMINI_API_KEY=你的_Gemini_API_Key
```

`dual` 保留中文原查詢，並加入 Gemini 產生的結構化英文醫療查詢；兩組
embeddings 批次查詢相同 collections，再以 RRF 合併、去重。`english` 只使用
英文查詢，適合 A/B 實驗，但不是預設建議。未設定時功能為 `off`。

送往 Gemini 前會遮蔽常見身分證、電話、Email、病歷號、姓名與地址標籤；回傳
必須符合固定 JSON Schema。API、格式或內容驗證失敗時，會自動退回多語
embedding 原查詢。log 只記錄是否翻譯、耗時與 variant，不記錄原文或翻譯內容。

一般 Gemini Developer API 的服務條款與資料治理不可直接視為符合臨床或個資
規範。正式病患流程啟用前仍需完成機構法務、資安、資料保護與醫療審查。

## 常見問題

### 為什麼 `backend/docs/` 仍有雜訊和大量空白？

它是不可變的原始爬蟲資料。請查看 `clean_docs/medical_articles.jsonl` 與
`clean_docs/cleaning_report.json`；若需要更進一步去除圖片、表格 UI 或修復
來源編碼，必須擴充 `scripts/clean_documents.py` 後重新執行完整 pipeline。

### 啟動後端時找不到 `chroma_db`

執行上述四個建置步驟，或使用 `./scripts/bootstrap.sh --with-rag`。若只重跑
清洗，既有 `classified_docs/` 與 `chroma_db/` 不會自動同步更新。
