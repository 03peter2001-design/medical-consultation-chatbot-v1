"""Canonical pain-location identifiers accepted by the patient chat API."""

BODY_PAIN_REGIONS = {
    # Detailed headache map
    "front_vertex": {"label": "頭頂", "view": "front"},
    "front_forehead_right": {"label": "右前額", "view": "front"},
    "front_forehead_left": {"label": "左前額", "view": "front"},
    "front_temple_right": {"label": "右太陽穴", "view": "front"},
    "front_temple_left": {"label": "左太陽穴", "view": "front"},
    "front_orbit_right": {"label": "右眼眶周圍", "view": "front"},
    "front_orbit_left": {"label": "左眼眶周圍", "view": "front"},
    "front_neck_right": {"label": "右前頸", "view": "front"},
    "front_neck_left": {"label": "左前頸", "view": "front"},
    "back_vertex": {"label": "頭頂後側", "view": "back"},
    "back_occipital_right": {"label": "右後腦", "view": "back"},
    "back_occipital_center": {"label": "後腦中央", "view": "back"},
    "back_occipital_left": {"label": "左後腦", "view": "back"},
    "back_neck_right": {"label": "右後頸", "view": "back"},
    "back_neck_center": {"label": "後頸中央", "view": "back"},
    "back_neck_left": {"label": "左後頸", "view": "back"},
    # Legacy coarse headache identifiers kept for existing records
    "front_head": {"label": "頭部前側", "view": "front"},
    "front_neck": {"label": "頸部前側", "view": "front"},
    "back_head": {"label": "後腦", "view": "back"},
    "back_neck": {"label": "後頸", "view": "back"},
    # Chest, abdomen and complete-body map
    "front_chest_right": {"label": "右胸", "view": "front"},
    "front_chest_center": {"label": "胸骨中央", "view": "front"},
    "front_chest_left": {"label": "左胸", "view": "front"},
    "front_upper_abdomen_right": {"label": "右上腹", "view": "front"},
    "front_upper_abdomen_center": {"label": "上腹中央", "view": "front"},
    "front_upper_abdomen_left": {"label": "左上腹", "view": "front"},
    "front_lower_abdomen_right": {"label": "右下腹", "view": "front"},
    "front_lower_abdomen_center": {"label": "下腹中央", "view": "front"},
    "front_lower_abdomen_left": {"label": "左下腹", "view": "front"},
    "front_arm_right": {"label": "右上肢", "view": "front"},
    "front_arm_left": {"label": "左上肢", "view": "front"},
    "front_leg_right": {"label": "右下肢", "view": "front"},
    "front_leg_left": {"label": "左下肢", "view": "front"},
    "back_upper_right": {"label": "右上背", "view": "back"},
    "back_spine_upper": {"label": "上背脊椎", "view": "back"},
    "back_upper_left": {"label": "左上背", "view": "back"},
    "back_flank_right": {"label": "右後腰", "view": "back"},
    "back_spine_lower": {"label": "下背脊椎", "view": "back"},
    "back_flank_left": {"label": "左後腰", "view": "back"},
    "back_hip_right": {"label": "右臀部", "view": "back"},
    "back_hip_left": {"label": "左臀部", "view": "back"},
    "back_arm_right": {"label": "右上肢後側", "view": "back"},
    "back_arm_left": {"label": "左上肢後側", "view": "back"},
    "back_leg_right": {"label": "右下肢後側", "view": "back"},
    "back_leg_left": {"label": "左下肢後側", "view": "back"},
}


def validate_pain_location_ids(
    location_ids: list[str],
    max_locations: int = 50,
) -> list[str]:
    if len(location_ids) > max_locations:
        raise ValueError("疼痛位置數量超過上限")

    unique = []
    for location_id in location_ids:
        if location_id not in BODY_PAIN_REGIONS:
            raise ValueError(f"未知的疼痛位置：{location_id}")
        if location_id not in unique:
            unique.append(location_id)
    return unique


def serialize_pain_locations(location_ids: list[str]) -> list[dict]:
    return [{"id": location_id, **BODY_PAIN_REGIONS[location_id]} for location_id in location_ids]
