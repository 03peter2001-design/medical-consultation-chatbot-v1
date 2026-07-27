import tempfile
import unittest
from pathlib import Path

from clean_documents import clean_corpus


ARTICLE = """
** Article URL: https://example.test/article/1-overview **

Example Disease: Background, Epidemiology

News & Perspective
References
Overview
Background
This is a clinically meaningful paragraph about a disease. It contains enough
information to remain in the cleaned corpus and should not be discarded.
[1]
[2] J
Next:
Clinical Presentation
Patients may have fever, cough, fatigue, and other relevant clinical findings.
Previous
References
Author One. Example reference.
References
Find Us On
"""


class CleanCorpusTests(unittest.TestCase):
    def test_keeps_body_and_removes_page_noise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir)
            for filename in (
                "Emergency_Medicine_Articles.txt",
                "Infectious_Diseases_Articles.txt",
                "Laboratory_Medicine_Articles.txt",
            ):
                (docs_dir / filename).write_text(ARTICLE, encoding="utf-8")

            articles, report = clean_corpus(docs_dir)

        self.assertEqual(len(articles), 1)
        text = articles[0]["text"]
        self.assertIn("clinically meaningful", text)
        self.assertIn("Clinical Presentation", text)
        self.assertNotIn("Next:", text)
        self.assertNotIn("Previous", text)
        self.assertNotIn("Author One", text)
        self.assertEqual(
            articles[0]["source_tags"],
            ["em", "id", "lab"],
        )
        self.assertEqual(
            report["statistics"]["duplicate_urls_merged"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
