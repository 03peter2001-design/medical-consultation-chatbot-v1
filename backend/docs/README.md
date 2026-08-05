# RAG 原始語料

此目錄保存三份 Medscape 爬蟲原始檔，作為可稽核、可重建的 RAG input：

- `Emergency_Medicine_Articles.txt`
- `Infectious_Diseases_Articles.txt`
- `Laboratory_Medicine_Articles.txt`

這些檔案不會被清洗器原地改寫，因此保留原始空白、控制字元、網站 UI 文字與
既有編碼損壞是預期行為。請勿把它們當成實際送入分類或向量索引的成品。

在 `backend/` 執行：

```bash
python -m scripts.clean_documents
```

結果會寫入 `../clean_docs/medical_articles.jsonl`，統計寫入
`../clean_docs/cleaning_report.json`。後續分類、建庫、清洗邊界與疑難排解請見
[../knowledge/README.md](../knowledge/README.md)。
