"""
將 Medscape 爬蟲文字轉成可稽核、可重建的 RAG 語料。

原始檔永遠保持不變；輸出為一行一篇文章的 JSONL，另附清洗統計報告。

執行方式：
    cd backend
    python -m scripts.clean_documents
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_DIR = BASE_DIR / "docs"
DEFAULT_OUTPUT = BASE_DIR / "clean_docs" / "medical_articles.jsonl"
DEFAULT_REPORT = BASE_DIR / "clean_docs" / "cleaning_report.json"

SOURCE_DEFINITIONS = (
    {
        "filename": "Emergency_Medicine_Articles.txt",
        "label": "Emergency Medicine (Medscape)",
        "tag": "em",
    },
    {
        "filename": "Infectious_Diseases_Articles.txt",
        "label": "Infectious Diseases (Medscape)",
        "tag": "id",
    },
    {
        "filename": "Laboratory_Medicine_Articles.txt",
        "label": "Laboratory Medicine (Medscape)",
        "tag": "lab",
    },
)

ARTICLE_SEPARATOR = re.compile(r"\*\*\s*Article URL:\s*(https?://\S+?)\s*\*\*")
UPDATED_PATTERN = re.compile(r"^Updated:\s*(.+)$", re.IGNORECASE)
CITATION_ONLY_PATTERN = re.compile(r"^\[(?:\d+(?:\s*[-–,]\s*\d+)*)\]$")
CITATION_PATTERN = re.compile(r"\s*\[(?:\d+(?:\s*[-–,]\s*\d+)*)\]\s*")

# 這些字串是網站控制項或圖片佔位符，不具有醫療語意。
DROP_EXACT = {
    "previous",
    "next",
    "next:",
    "show all",
    "view media gallery",
    "j",
}


class CleaningError(RuntimeError):
    """原始文章不符合已知 Medscape 頁面結構。"""


def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalise_line(line: str, stats: Counter) -> str:
    line = unicodedata.normalize("NFC", line)
    cleaned_chars = []

    for char in line:
        category = unicodedata.category(char)
        if category.startswith("C"):
            stats["control_characters_removed"] += 1
            cleaned_chars.append(" ")
        elif char == "\ufffd":
            stats["replacement_characters_removed"] += 1
            cleaned_chars.append(" ")
        else:
            cleaned_chars.append(char)

    line = "".join(cleaned_chars).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", line).strip()


def _nonempty_lines(text: str, stats: Counter) -> list[str]:
    lines = []
    for raw_line in _normalise_newlines(text).splitlines():
        line = _normalise_line(raw_line, stats)
        if line:
            lines.append(line)
        else:
            stats["blank_lines_removed"] += 1
    return lines


def _extract_article(
    url: str,
    raw_article: str,
    source: dict,
    stats: Counter,
) -> dict:
    lines = _nonempty_lines(raw_article, stats)
    if not lines:
        raise CleaningError("文章沒有非空白內容")

    title = lines[0]
    updated = ""
    for line in lines:
        match = UPDATED_PATTERN.match(line)
        if match:
            updated = match.group(1).strip()
            break

    # 這批 Medscape 頁面固定依序包含：
    # 1. 導覽列 References
    # 2. 正文結束後的 References
    # 3. 頁尾重複導覽列 References
    # 只保留第一與第二個標記之間的正文。
    reference_indexes = [
        index for index, line in enumerate(lines) if line.casefold() == "references"
    ]
    if len(reference_indexes) < 2:
        raise CleaningError(f"找不到正文邊界（References 出現 {len(reference_indexes)} 次）")

    body_lines = lines[reference_indexes[0] + 1 : reference_indexes[1]]
    cleaned_lines: list[str] = []

    for line in body_lines:
        folded = line.casefold()
        if folded in DROP_EXACT:
            stats[f"dropped_marker:{folded}"] += 1
            continue
        if CITATION_ONLY_PATTERN.fullmatch(line):
            stats["standalone_citations_removed"] += 1
            continue

        line, citation_count = CITATION_PATTERN.subn(" ", line)
        stats["inline_citations_removed"] += citation_count
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if line.casefold() in DROP_EXACT:
            stats[f"dropped_marker:{line.casefold()}"] += 1
            continue

        # 相鄰重複行通常來自響應式頁面重複渲染。
        if cleaned_lines and line == cleaned_lines[-1]:
            stats["adjacent_duplicate_lines_removed"] += 1
            continue
        cleaned_lines.append(line)

    text = "\n\n".join(cleaned_lines).strip()
    if len(text) < 200:
        raise CleaningError(f"清洗後正文過短（{len(text)} 字元）")

    return {
        "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:20],
        "url": url,
        "title": title,
        "updated": updated,
        "source_tags": [source["tag"]],
        "source_labels": [source["label"]],
        "text": text,
    }


def _iter_raw_articles(raw: str) -> Iterable[tuple[str, str]]:
    parts = ARTICLE_SEPARATOR.split(_normalise_newlines(raw))
    for index in range(1, len(parts) - 1, 2):
        yield parts[index].strip(), parts[index + 1]


def clean_corpus(
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> tuple[list[dict], dict]:
    stats: Counter = Counter()
    per_source: dict[str, dict] = {}
    by_url: dict[str, dict] = {}
    rejected: list[dict] = []

    for source in SOURCE_DEFINITIONS:
        path = docs_dir / source["filename"]
        if not path.exists():
            rejected.append(
                {
                    "source": source["filename"],
                    "url": "",
                    "reason": "找不到來源檔案",
                }
            )
            continue

        raw = path.read_text(encoding="utf-8", errors="replace")
        source_count = 0
        accepted_count = 0

        for url, raw_article in _iter_raw_articles(raw):
            source_count += 1
            stats["raw_articles"] += 1
            try:
                article = _extract_article(url, raw_article, source, stats)
            except CleaningError as exc:
                rejected.append(
                    {
                        "source": source["filename"],
                        "url": url,
                        "reason": str(exc),
                    }
                )
                stats["rejected_articles"] += 1
                continue

            accepted_count += 1
            existing = by_url.get(url)
            if existing is None:
                by_url[url] = article
                continue

            stats["duplicate_urls_merged"] += 1
            tags = sorted(set(existing["source_tags"] + article["source_tags"]))
            labels = sorted(set(existing["source_labels"] + article["source_labels"]))

            # 同一網址可能是在不同時間或分類下爬取；保留正文較完整者，
            # 同時合併分類 metadata，避免重複建立向量。
            if len(article["text"]) > len(existing["text"]):
                article["source_tags"] = tags
                article["source_labels"] = labels
                by_url[url] = article
            else:
                existing["source_tags"] = tags
                existing["source_labels"] = labels

        per_source[source["tag"]] = {
            "filename": source["filename"],
            "raw_articles": source_count,
            "accepted_before_deduplication": accepted_count,
        }

    articles = sorted(by_url.values(), key=lambda item: item["url"])
    stats["unique_articles"] = len(articles)
    stats["output_characters"] = sum(len(article["text"]) for article in articles)

    report = {
        "schema_version": 1,
        "source_directory": str(docs_dir),
        "per_source": per_source,
        "statistics": dict(sorted(stats.items())),
        "rejected": rejected,
    }
    return articles, report


def write_clean_corpus(
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> tuple[list[dict], dict]:
    articles, report = clean_corpus(docs_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for article in articles:
            stream.write(json.dumps(article, ensure_ascii=False, sort_keys=True))
            stream.write("\n")

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return articles, report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="清洗三份 Medscape 爬蟲文字，輸出 RAG JSONL 語料。"
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DEFAULT_DOCS_DIR,
        help="原始 .txt 所在目錄",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="清洗後 JSONL 路徑",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="清洗統計 JSON 路徑",
    )
    args = parser.parse_args()

    articles, report = write_clean_corpus(
        output_path=args.output,
        report_path=args.report,
        docs_dir=args.docs_dir,
    )
    statistics = report["statistics"]
    print(f"原始文章：{statistics.get('raw_articles', 0)}")
    print(f"合併重複 URL：{statistics.get('duplicate_urls_merged', 0)}")
    print(f"清洗後文章：{len(articles)}")
    print(f"拒絕文章：{statistics.get('rejected_articles', 0)}")
    print(f"輸出：{args.output}")
    print(f"報告：{args.report}")


if __name__ == "__main__":
    main()
