"""Development-only synthetic consultation used by the physician UI."""

from app.runtime import consultation_repository
from app.services.clinical_summary import build_summary

TEST_PATIENT_QUEUE_NUMBER = "00000"


def seed_test_patient() -> None:
    test_data = {
        "type": "chest",
        "name": "測試病人",
        "gender": "男性",
        "age": "52",
        "reason": "胸痛",
        "onset": "30分鐘前",
        "onset_num": "30",
        "onset_unit": "分鐘前",
        "start_type": "突然發作",
        "location": "左邊",
        "pain_locations": [
            {
                "id": "front_chest_left",
                "label": "左胸",
                "view": "front",
            }
        ],
        "fixed": "痛點固定",
        "tender": "沒有",
        "quality": "感覺有重物壓迫",
        "aggravate": "耗費體力的活動",
        "relieve": "休息",
        "associated": "冒冷汗，感到心跳加速或不規則",
        "smoke": "過去有抽，但已戒菸",
        "cardio": "高血壓",
        "chronic": "以上皆無",
        "past_meds": "以上皆無",
        "surgery": "未曾手術",
        "current_meds": "沒有",
        "allergy": "沒有",
    }
    report = (
        "【基本資料】\n男性／52歲\n\n"
        "【主訴】\n30分鐘前突然發作的左側胸痛，痛點固定，感覺有重物壓迫\n\n"
        "【伴隨症狀】\n冒冷汗、心跳加速或不規則\n\n"
        "【過去病史】\n高血壓，過去有抽菸但已戒菸，未曾手術，目前無用藥\n\n"
        "【初步評估】\n（測試資料：此內容為預先寫死，非實際模型生成）\n\n"
        "【建議】\n建議立即就醫評估，排除急性冠心症候群等致命病因。\n\n"
        "※ 此為測試用假病人資料，非真實病人。"
    )
    consultation_repository.upsert_fixed(
        TEST_PATIENT_QUEUE_NUMBER,
        {
            "queue_number": TEST_PATIENT_QUEUE_NUMBER,
            "type": "chest",
            "reason": test_data["reason"],
            "summary": build_summary(test_data),
            "report": report,
            "data": test_data,
            "status": "synthetic_test",
        },
    )
    print(f"[Seed] 已建立測試病人，問診編號：{TEST_PATIENT_QUEUE_NUMBER}")
