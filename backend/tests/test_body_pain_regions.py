import unittest

from domain.body_pain_regions import (
    serialize_pain_locations,
    validate_pain_location_ids,
)


class BodyPainRegionTests(unittest.TestCase):
    def test_accepts_and_serializes_detailed_head_locations(self):
        location_ids = validate_pain_location_ids(
            [
                "front_vertex",
                "front_temple_right",
                "back_occipital_center",
                "back_neck_left",
            ]
        )

        self.assertEqual(
            serialize_pain_locations(location_ids),
            [
                {"id": "front_vertex", "label": "頭頂", "view": "front"},
                {
                    "id": "front_temple_right",
                    "label": "右太陽穴",
                    "view": "front",
                },
                {
                    "id": "back_occipital_center",
                    "label": "後腦中央",
                    "view": "back",
                },
                {
                    "id": "back_neck_left",
                    "label": "左後頸",
                    "view": "back",
                },
            ],
        )

    def test_deduplicates_locations_and_keeps_legacy_ids(self):
        self.assertEqual(
            validate_pain_location_ids(["front_head", "front_head", "back_neck"]),
            ["front_head", "back_neck"],
        )

    def test_rejects_unknown_locations(self):
        with self.assertRaisesRegex(ValueError, "未知的疼痛位置"):
            validate_pain_location_ids(["front_unknown"])


if __name__ == "__main__":
    unittest.main()
