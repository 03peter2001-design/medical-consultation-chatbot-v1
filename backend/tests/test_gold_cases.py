import json
import unittest
from pathlib import Path

from rag import select_routes


class GoldCaseTests(unittest.TestCase):
    def test_gold_set_has_required_coverage(self):
        path = Path(__file__).parent / "data" / "rag_gold_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 45)

        counts = {"chest": 0, "headache": 0, "abdomen": 0}
        red_flags = 0
        for case in cases:
            self.assertTrue(case["must_include_any"])
            self.assertIn("safety", case["expected_routes"])
            self.assertEqual(
                set(case),
                {
                    "id",
                    "query",
                    "primary_route",
                    "purpose",
                    "expected_routes",
                    "must_include_any",
                    "forbidden_terms",
                }
                | ({"red_flag"} if case.get("red_flag") else set()),
            )
            if case.get("red_flag"):
                red_flags += 1
            else:
                counts[case["primary_route"]] += 1
            selected = select_routes(
                case["query"],
                primary_route=case["primary_route"],
                purpose=case["purpose"],
            )
            self.assertTrue(
                set(case["expected_routes"]).issubset(selected),
                msg=f"{case['id']} expected {case['expected_routes']}, got {selected}",
            )

        self.assertEqual(counts, {"chest": 12, "headache": 12, "abdomen": 12})
        self.assertEqual(red_flags, 9)


if __name__ == "__main__":
    unittest.main()
