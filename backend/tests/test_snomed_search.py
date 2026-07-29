import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.snomed_search import search_snomed


def fhir_response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class SnomedSearchTests(unittest.TestCase):
    def test_text_search_uses_local_rf2_index(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snomed.sqlite3"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO metadata VALUES ('release_date', '20250701');
                CREATE TABLE concepts (code TEXT PRIMARY KEY, display TEXT NOT NULL);
                INSERT INTO concepts VALUES (
                    '394659003',
                    'Acute coronary syndrome'
                );
                CREATE VIRTUAL TABLE terms USING fts5(code UNINDEXED, term);
                INSERT INTO terms VALUES (
                    '394659003',
                    'Acute coronary syndrome'
                );
                """
            )
            connection.close()
            with patch.dict(
                os.environ,
                {"SNOMED_SEARCH_DB": str(database_path)},
            ):
                result = search_snomed("acute coronary syndrome")

        self.assertEqual(result["source"], "local-rf2-index")
        self.assertEqual(result["release_date"], "20250701")
        self.assertEqual(result["items"][0]["code"], "394659003")

    def test_numeric_search_uses_code_system_lookup(self):
        payload = {
            "resourceType": "Parameters",
            "parameter": [
                {
                    "name": "display",
                    "valueString": "Migraine (disorder)",
                }
            ],
        }
        with patch(
            "app.services.snomed_search.urllib.request.urlopen",
            return_value=fhir_response(payload),
        ) as urlopen:
            result = search_snomed("37796009")

        request = urlopen.call_args.args[0]
        self.assertIn("CodeSystem/$lookup", request.full_url)
        self.assertEqual(result["mode"], "code")
        self.assertEqual(result["items"][0]["display"], "Migraine (disorder)")

    def test_rejects_too_short_query(self):
        with self.assertRaisesRegex(ValueError, "至少 2 個"):
            search_snomed("a")


if __name__ == "__main__":
    unittest.main()
