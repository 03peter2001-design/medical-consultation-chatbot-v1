"""
rag.py — RAG 查詢模組，供 main.py 呼叫
"""

import chromadb
from chromadb.utils import embedding_functions
import os

CHROMA_DIR = "./chroma_db"
_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        if not os.path.exists(CHROMA_DIR):
            raise RuntimeError(
                "找不到向量資料庫，請先執行 python ingest.py"
            )
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )
        _collection = client.get_collection(
            name="medical_kb",
            embedding_function=ef
        )
    return _collection


def retrieve(query: str, n_results: int = 5) -> list[dict]:
    """
    根據查詢字串，從向量庫找出最相關的段落
    回傳: [{"text": ..., "source": ..., "chapter": ...}, ...]
    """
    try:
        col = _get_collection()
        results = col.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        retrieved = []
        for doc, meta, dist in zip(docs, metas, distances):
            # cosine distance < 0.6 才納入（太遠的不用）
            if dist < 0.6:
                retrieved.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                    "distance": round(dist, 3)
                })
        return retrieved
    except Exception as e:
        print(f"[RAG] 查詢失敗: {e}")
        return []


def _build_chest_query(patient_data: dict) -> str:
    parts = []

    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    if onset:
        parts.append(f"chest pain {onset}")

    quality = patient_data.get("quality", "")
    if quality:
        parts.append(quality)

    aggravate = patient_data.get("aggravate", "")
    if aggravate:
        parts.append(aggravate)

    associated = patient_data.get("associated", "")
    if associated:
        parts.append(associated)

    cardio = patient_data.get("cardio", "")
    if cardio and cardio != "以上皆無":
        parts.append(cardio)

    return " ".join(parts) if parts else "chest pain diagnosis differential"


def _build_headache_query(patient_data: dict) -> str:
    parts = ["headache"]

    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    if onset:
        parts.append(onset)

    start_type = patient_data.get("start_type", "")
    if start_type:
        parts.append(start_type)

    worst_ever = patient_data.get("worst_ever", "")
    if worst_ever and ("是" in worst_ever or "前所未有" in worst_ever):
        parts.append("thunderclap headache worst headache of life")

    quality = patient_data.get("quality", "")
    if quality:
        parts.append(quality)

    associated = patient_data.get("associated", "")
    if associated:
        parts.append(associated)
        if "頸部僵硬" in associated or "發燒" in associated:
            parts.append("meningitis neck stiffness fever")
        if "單側肢體無力" in associated or "言語不清" in associated:
            parts.append("stroke focal neurologic deficit")
        if "視力模糊" in associated or "複視" in associated:
            parts.append("papilledema vision changes")

    risk_flags = patient_data.get("risk_flags", "")
    if risk_flags and risk_flags != "以上皆無":
        parts.append(risk_flags)
        if "外傷" in risk_flags:
            parts.append("head trauma")
        if "免疫" in risk_flags or "癌症" in risk_flags:
            parts.append("immunocompromised malignancy")
        if "抗凝血" in risk_flags:
            parts.append("anticoagulant intracranial hemorrhage")
        if "懷孕" in risk_flags:
            parts.append("pregnancy postpartum")

    neuro = patient_data.get("neuro", "")
    if neuro and neuro != "以上皆無":
        parts.append(neuro)
        if "顳動脈炎" in neuro:
            parts.append("temporal arteritis giant cell arteritis jaw claudication")

    return " ".join(parts) if parts else "headache differential diagnosis red flags"


def _build_abdomen_query(patient_data: dict) -> str:
    parts = ["abdominal pain"]

    onset = f"{patient_data.get('onset_num', '')} {patient_data.get('onset_unit', '')}".strip()
    if onset:
        parts.append(onset)

    location = patient_data.get("location", "")
    if location:
        parts.append(location)
        if "右下腹" in location or "肚臍" in location:
            parts.append("appendicitis")
        if "右上腹" in location:
            parts.append("cholecystitis biliary colic")
        if "腰痛" in location:
            parts.append("renal colic pyelonephritis")

    quality = patient_data.get("quality", "")
    if quality:
        parts.append(quality)
        if "肚臍" in quality and "右下腹" in quality:
            parts.append("appendicitis migratory pain")
        if "由前痛到背後" in quality:
            parts.append("pancreatitis aortic dissection")

    associated = patient_data.get("associated", "")
    if associated and associated != "以上皆無":
        parts.append(associated)
        if "血便" in associated:
            parts.append("GI bleeding")
        if "血尿" in associated:
            parts.append("urinary tract infection kidney stone")
        if "月經過期" in associated or "陰道分泌物增加" in associated:
            parts.append("ectopic pregnancy pelvic inflammatory disease")

    abdomen_hx = patient_data.get("abdomen_hx", "")
    if abdomen_hx and abdomen_hx != "以上皆無":
        parts.append(abdomen_hx)
        if "腹主動脈瘤" in abdomen_hx:
            parts.append("abdominal aortic aneurysm rupture")
        if "糖尿病酮酸中毒" in abdomen_hx:
            parts.append("diabetic ketoacidosis")

    return " ".join(parts) if parts else "abdominal pain differential diagnosis"


def build_context(patient_data: dict, ctype: str = "chest") -> str:
    """
    根據病患資料（胸痛／頭痛／腹痛問卷）組合查詢字串，撈出相關醫學知識
    回傳給 LLM 的 context 字串
    """
    if ctype == "headache":
        query = _build_headache_query(patient_data)
    elif ctype == "abdomen":
        query = _build_abdomen_query(patient_data)
    else:
        query = _build_chest_query(patient_data)

    # 查詢向量庫
    chunks = retrieve(query, n_results=6)

    if not chunks:
        return ""

    # 整理成 context 文字（同一篇文章只取一段，避免重複）
    context_parts = []
    seen_titles = set()
    for chunk in chunks:
        title = chunk["title"]
        if title in seen_titles:
            continue
        seen_titles.add(title)
        context_parts.append(
            f"[{chunk['source']} — {chunk['title']}]\n{chunk['text'][:800]}"
        )

    return "\n\n---\n\n".join(context_parts)
