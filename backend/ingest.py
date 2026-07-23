"""
ingest.py — 從三份 Medscape 文字檔建立 RAG 向量索引
來源：Emergency Medicine / Infectious Diseases / Laboratory Medicine
執行方式：python ingest.py
（把三份 .txt 放到 backend/docs/ 資料夾後執行）
"""

import chromadb
from chromadb.utils import embedding_functions
import re, os

# ── 設定 ──────────────────────────────────────────────────
# 用絕對路徑（相對於這個檔案的所在位置），這樣不管從哪個目錄執行
# `python ingest.py`，都會讀到／寫到 backend/ 底下正確的資料夾，
# 且跟 rag.py 讀取的 CHROMA_DIR 保證是同一個地方。
_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR    = os.path.join(_BASE_DIR, "chroma_db")
CHUNK_SIZE    = 600
CHUNK_OVERLAP = 200

SOURCE_FILES = [
    {
        "path":  os.path.join(_BASE_DIR, "docs", "Emergency_Medicine_Articles.txt"),
        "label": "Emergency Medicine (Medscape)",
        "tag":   "em",
    },
    {
        "path":  os.path.join(_BASE_DIR, "docs", "Infectious_Diseases_Articles.txt"),
        "label": "Infectious Diseases (Medscape)",
        "tag":   "id",
    },
    {
        "path":  os.path.join(_BASE_DIR, "docs", "Laboratory_Medicine_Articles.txt"),
        "label": "Laboratory Medicine (Medscape)",
        "tag":   "lab",
    },
]

ARTICLE_SEP = re.compile(r'\*\* Article URL: (https?://\S+) \*\*')

# 章節標題（導覽列），出現後略過整行
NAV_TITLES = re.compile(
    r'^(Show All|DDx|Workup|Presentation|Overview|Follow-up|Medication|'
    r'Treatment|References|Sections|History|Physical|Causes|Guidelines|'
    r'Media Gallery|Tables|Questions & Answers|Back to List|'
    r'Contributor Information|Author|Coauthor|Chief Editor|'
    r'Specialty Editor Board|Additional Contributors|Acknowledgements|'
    r'Find Us On|About|Membership|App|WebMD Network|Editions|'
    r'Drug Interaction Checker|Pill Identifier|Calculators|Formulary|'
    r'Slideshow|Recommended|Related Conditions|News & Perspective)$',
    re.IGNORECASE
)


def extract_body(raw_body: str) -> tuple[str, str]:
    """
    從單篇文章的原始文字中：
    1. 取出標題（Medscape 文章標題行）
    2. 取出正文（第一個超過100字的段落開始）
    並清除多餘的導覽列殘留。
    """
    # 找「標題行」：通常在第一個 \n\n 之後的第一個包含冒號的長行
    title_match = re.search(r'\n\n([^\n]{10,120}:[^\n]{0,80})\n', raw_body)
    title = title_match.group(1).strip() if title_match else ""

    # 找第一個「正文段落」：雙換行後，一個超過100字的段落
    body_match = re.search(r'\n\n([A-Z][^\n]{100,})', raw_body)
    if not body_match:
        return title, ""

    text = raw_body[body_match.start():]

    # 刪除 References 章節以後的內容（只要 References 單獨佔一行）
    text = re.sub(r'\n\nReferences\n.*', '', text, flags=re.DOTALL)

    # 清除 \r
    text = text.replace('\r', '')
    # 壓縮多餘空白行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return title, text.strip()


def split_articles(raw: str) -> list[dict]:
    parts = ARTICLE_SEP.split(raw)
    articles = []
    for i in range(1, len(parts) - 1, 2):
        url   = parts[i].strip()
        title, body_text = extract_body(parts[i + 1])
        if len(body_text) < 200:
            continue
        articles.append({"url": url, "title": title or url, "text": body_text})
    return articles


def chunk_text(text: str) -> list[str]:
    paragraphs = re.split(r'\n\n+', text)
    chunks, current = [], ""

    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 20:
            continue
        if len(current) + len(para) + 1 <= CHUNK_SIZE:
            current += (" " if current else "") + para
        else:
            if current:
                chunks.append(current.strip())
            if len(para) > CHUNK_SIZE:
                words, sub = para.split(), ""
                for w in words:
                    if len(sub) + len(w) + 1 <= CHUNK_SIZE:
                        sub += (" " if sub else "") + w
                    else:
                        if sub:
                            chunks.append(sub.strip())
                        # 強制切割時也帶入前段尾巴作為 overlap
                        if chunks and CHUNK_OVERLAP > 0:
                            prev_tail = " ".join(chunks[-1].split()[-(CHUNK_OVERLAP // 6):])
                            sub = prev_tail + " " + w
                        else:
                            sub = w
                current = sub
            else:
                if chunks and CHUNK_OVERLAP > 0:
                    prev_tail = " ".join(chunks[-1].split()[-(CHUNK_OVERLAP // 6):])
                    current = prev_tail + " " + para
                else:
                    current = para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c) > 60]


def main():
    print("=" * 60)
    print("RAG Ingest — Medscape EM / ID / Lab Medicine")
    print("=" * 60)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"
    )

    try:
        client.delete_collection("medical_kb")
        print("舊 collection 已清除")
    except Exception:
        pass

    collection = client.create_collection(
        name="medical_kb",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    all_docs, all_ids, all_metas = [], [], []
    idx = 0

    for src in SOURCE_FILES:
        if not os.path.exists(src["path"]):
            print(f"\n⚠️  找不到 {src['path']}，略過")
            continue

        print(f"\n[{src['tag'].upper()}] 處理 {src['label']}...")
        raw      = open(src["path"], encoding="utf-8", errors="replace").read()
        articles = split_articles(raw)
        print(f"  → 解析出 {len(articles)} 篇文章")

        art_chunks = 0
        for art in articles:
            for chunk in chunk_text(art["text"]):
                all_docs.append(chunk)
                all_ids.append(f"{src['tag']}_{idx}")
                all_metas.append({
                    "source": src["label"],
                    "title":  art["title"][:120],
                    "url":    art["url"],
                })
                idx += 1
                art_chunks += 1

        print(f"  → {art_chunks} chunks")

    print(f"\n寫入向量庫（共 {len(all_docs)} chunks）...")
    BATCH = 64
    for i in range(0, len(all_docs), BATCH):
        collection.add(
            documents=all_docs[i : i + BATCH],
            ids=all_ids[i : i + BATCH],
            metadatas=all_metas[i : i + BATCH],
        )
        print(f"  {min(i + BATCH, len(all_docs))}/{len(all_docs)}", end="\r")

    print(f"\n✅ 完成！共 {len(all_docs)} 個向量段落存入 {CHROMA_DIR}/")
    print("請執行：uvicorn main:app --reload")


if __name__ == "__main__":
    main()
