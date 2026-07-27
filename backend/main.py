from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv
from llm import LLMClient
from questionnaires import (
    CHIEF_QUESTIONNAIRE,
    ROUTE_LABELS,
    build_questionnaire,
    next_question_index,
    parse_birth_date,
    parse_onset_answer,
    progress_meta,
    question_input as structured_question_input,
    questionnaire_meta,
)
import os
import re
import time
import random
import traceback

load_dotenv()

app = FastAPI(title="AI 預問診系統", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_client = LLMClient()
print(f"[LLM] 使用 {llm_client.provider}（{llm_client.model}）")

sessions: dict[str, dict] = {}
SESSION_TTL = 60 * 30

# ── 醫師端 RAG 聊天 session ──────────────────────────────
doctor_sessions: dict[str, dict] = {}
DOCTOR_SESSION_TTL = 60 * 60
DOCTOR_HISTORY_MAX_TURNS = 8  # 保留最近 8 輪對話

# ── 問診編號 → 病人資料（供醫師端輸入編號查詢）──────────────
patient_records: dict[str, dict] = {}
PATIENT_RECORD_TTL = 60 * 60 * 8  # 保留 8 小時（一個班次）

def generate_queue_number(ctype: str) -> str:
    while True:
        num = f"{random.randint(0, 99999):05d}"
        if num not in patient_records:
            return num


def _cleanup_patient_records():
    now = time.time()
    expired = [
        k for k, v in patient_records.items()
        if k != "00000" and now - v.get("ts", 0) > PATIENT_RECORD_TTL
    ]
    for k in expired:
        del patient_records[k]

# ── RAG ──────────────────────────────────────────────────
RAG_ENABLED = False
RAG_STATUS = {
    "enabled": False,
    "index_version": "unavailable",
    "collections": [],
    "legacy_available": False,
}
try:
    from rag import build_context, get_rag_status, retrieve

    RAG_STATUS = get_rag_status()
    RAG_ENABLED = RAG_STATUS["enabled"]
    if RAG_ENABLED:
        print(
            "[RAG] 向量庫已啟用："
            f"version={RAG_STATUS['index_version']} "
            f"collections={RAG_STATUS['collections']}"
        )
    else:
        print(f"[RAG] 找不到完整的作用中索引：{RAG_STATUS}")
except Exception as e:
    print(f"[RAG] 初始化失敗，RAG 停用：{e}")

# ── Whisper prompt ───────────────────────────────────────
WHISPER_PROMPT = (
    "繁體中文醫療問診，請輸出繁體中文。"
    "性別:男、女、"
    "常見詞：胸痛、胸悶、心絞痛、心肌梗塞、心臟衰竭、心律不整、主動脈剝離、"
    "肺栓塞、肺高壓、心包膜積水、氣胸、中風、高血壓、糖尿病、高血脂、"
    "心臟支架、心臟血管繞道手術、心律調節器、"
    "阿斯匹靈、硝酸甘油、類固醇、"
    "刺痛、鈍痛、壓迫感、呼吸急促、冒冷汗、噁心、嘔吐、昏厥、頭暈、"
    "突然發作、逐漸發作、痛點固定、以上皆無、未曾手術、已戒菸、"
    "數字用阿拉伯數字。"
)

# ── 性別辨識專用同音字清單 ─────────────────────────────
MALE_SOUNDALIKES = ["南", "難", "藍"]       # 男 (nán) 常見諧音誤聽
FEMALE_SOUNDALIKES = ["努", "怒", "呂"]     # 女 (nǚ) 常見諧音誤聽

CORRECTION_MAP = {
    "心腳痛": "心絞痛", "心角痛": "心絞痛", "心較痛": "心絞痛", "心教痛": "心絞痛",
    "常尿病": "糖尿病", "糖尿兵": "糖尿病", "高血壓病": "高血壓",
    "肺拴塞": "肺栓塞", "肺門高壓": "肺高壓", "心包膜積液": "心包膜積水", "主動脈剝皮": "主動脈剝離",
    "以上都沒有": "以上皆無", "都沒有": "以上皆無", "沒有以上": "以上皆無", "上街舞": "以上皆無",
    "沒有手術": "未曾手術", "沒做過手術": "未曾手術",
    "心臟架": "心臟支架", "心臟支加": "心臟支架", "心臟之架": "心臟支架",
    "血管繞道": "心臟血管繞道手術", "心律節律器": "心律調節器", "心律節律機": "心律調節器",
    "頓痛": "鈍痛", "純痛": "鈍痛", "重物壓迫": "有重物壓迫感",
    "呼吸不順": "感到呼吸急促", "心跳快": "心跳加速或不規則", "心跳不規則": "心跳加速或不規則",
    "冷汗": "冒冷汗",
    "以戒菸": "已戒菸", "具有抽但以戒菸": "過去有抽，但已戒菸",
    "過去有抽以戒菸": "過去有抽，但已戒菸", "有抽已戒": "過去有抽，但已戒菸",
    "阿斯P": "阿斯匹靈", "阿斯匹": "阿斯匹靈", "阿斯比": "阿斯匹靈", "硝酸甘": "硝酸甘油",
    "風。": "否", "嗨。": "心臟支架",
}

_SYMPTOM_PHRASE_RULES = [
    (("噁心", "嘔吐"), "感到噁心或已嘔吐"),
    (("昏厥", "頭暈"), "有昏厥或頭暈感"),
]


def _apply_symptom_phrases(text: str) -> str:
    for keywords, phrase in _SYMPTOM_PHRASE_RULES:
        if any(k in text for k in keywords):
            for k in keywords:
                text = text.replace(k, "")
            text = text + phrase
    return text


_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100}
_CN_NUM_PATTERN = re.compile(r"[零一二三四五六七八九十百]+")


def _cn_to_int(s: str):
    if s[0] == "十":
        s = "一" + s
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (num or 1) * _CN_UNIT[ch]
            num = 0
        else:
            return None
    return total + section + num


def _convert_chinese_numerals(text: str) -> str:
    def repl(m):
        val = _cn_to_int(m.group(0))
        return str(val) if val is not None else m.group(0)
    return _CN_NUM_PATTERN.sub(repl, text)

_JUNK_TRANSCRIPTIONS = {
    "", "。", "！", "？", "，", "、", "…",
    "お", "お...", "の", "ん", "あ", "え",
    "Uh", "Um", "Hmm",
}



def correct_transcription(text: str) -> str:
    corrected = text.strip()
    corrected = re.sub(r'([男女性]+)[１1]$', r'\1', corrected)

    if CORRECTION_MAP:
        pattern = re.compile(
            "|".join(re.escape(k) for k in sorted(CORRECTION_MAP.keys(), key=len, reverse=True))
        )
        corrected = pattern.sub(lambda m: CORRECTION_MAP[m.group(0)], corrected)

    corrected = _apply_symptom_phrases(corrected)
    corrected = _convert_chinese_numerals(corrected)
    corrected = corrected.rstrip("。！？，、")
    full2half = str.maketrans("０１２３４５６７８９", "0123456789")
    corrected = corrected.translate(full2half)

    corrected = re.sub(r'(阿斯匹靈){2,}', '阿斯匹靈', corrected)
    corrected = re.sub(r'(硝酸甘油){2,}', '硝酸甘油', corrected)
    corrected = re.sub(r'冒冒冷汗', '冒冷汗', corrected)
    corrected = re.sub(r'(冒冷汗){2,}', '冒冷汗', corrected)
    corrected = re.sub(r'(感到噁心或已嘔吐){2,}', '感到噁心或已嘔吐', corrected)
    corrected = re.sub(r'(有昏厥或頭暈感){2,}', '有昏厥或頭暈感', corrected)

    return corrected.strip()


def is_junk(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if re.match(r'^\d+$', t):
        return False
    if t in _JUNK_TRANSCRIPTIONS:
        return True
    if all(c in '。！？，、….' for c in t):
        return True
    if len(t) <= 2 and not re.search(r'[\u4e00-\u9fff]', t):
        return True
    return False


def _cleanup_sessions():
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s.get("ts", 0) > SESSION_TTL]
    for sid in expired:
        del sessions[sid]


class PatientPrefill(BaseModel):
    source: str = "fhir"
    name: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    blood_type: str | None = None
    smoke: str | None = None
    chronic: str | None = None
    past_meds: str | None = None
    current_meds: str | None = None
    allergy: str | None = None
    cardio: str | None = None
    neuro: str | None = None
    abdomen_hx: str | None = None
    surgery: str | None = None

    @validator(
        "name",
        "gender",
        "birth_date",
        "blood_type",
        "smoke",
        "chronic",
        "past_meds",
        "current_meds",
        "allergy",
        "cardio",
        "neuro",
        "abdomen_hx",
        "surgery",
    )
    def trim_prefill_value(cls, value):
        return value.strip()[:500] if value else None


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str
    pain_location_ids: list[str] = Field(default_factory=list)
    patient_prefill: PatientPrefill | None = None

    @validator("session_id")
    def session_id_not_empty(cls, v):
        if not v.strip():
            raise ValueError("session_id 不可為空")
        return v.strip()[:64]

    @validator("message")
    def message_length(cls, v):
        return v.strip()[:500]

    @validator("pain_location_ids")
    def pain_location_ids_valid(cls, v):
        if len(v) > 50:
            raise ValueError("疼痛位置數量超過上限")
        unique = []
        for value in v:
            if value not in BODY_PAIN_REGIONS:
                raise ValueError(f"未知的疼痛位置：{value}")
            if value not in unique:
                unique.append(value)
        return unique


BODY_PAIN_REGIONS = {
    "front_head": {"label": "頭部前側", "view": "front"},
    "front_neck": {"label": "頸部前側", "view": "front"},
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
    "back_head": {"label": "後腦", "view": "back"},
    "back_neck": {"label": "後頸", "view": "back"},
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


def serialize_pain_locations(location_ids: list[str]) -> list[dict]:
    return [
        {"id": location_id, **BODY_PAIN_REGIONS[location_id]}
        for location_id in location_ids
    ]


CHEST_KEYWORDS = ["胸痛", "胸悶", "胸緊", "胸壓", "胸口痛", "心口", "前胸", "胸部不適"]
HEADACHE_KEYWORDS = ["頭痛", "頭很痛", "頭暈痛", "偏頭痛", "頭脹", "頭部不適", "腦袋痛"]
ABDOMEN_KEYWORDS = ["肚子痛", "腹痛", "肚子不舒服", "腹部疼痛", "肚臍痛", "腹脹痛", "肚子", "胃痛"]


def is_chest_pain(text: str) -> bool:
    return any(kw in text for kw in CHEST_KEYWORDS)


def is_headache(text: str) -> bool:
    return any(kw in text for kw in HEADACHE_KEYWORDS)


def is_abdomen_pain(text: str) -> bool:
    return any(kw in text for kw in ABDOMEN_KEYWORDS)


def classify_complaint(text: str) -> str:
    """由 LLM 判斷主訴路由；只有 API 失敗或輸出無效時才用規則備援。"""
    hits = {
        "chest": is_chest_pain(text),
        "headache": is_headache(text),
        "abdomen": is_abdomen_pain(text),
    }
    matched = [k for k, v in hits.items() if v]

    try:
        result = llm_client.generate_text(
            [
                {
                    "role": "system",
                    "content": (
                        "你是急診分流護理師。請判斷病患描述的主訴最符合以下哪一類："
                        "chest（胸痛/胸悶/胸部相關不適）、headache（頭痛/頭部相關不適）、"
                        "abdomen（腹痛/肚子痛/腹部相關不適）、other（以上皆非）。"
                        "只能回傳一個英文單字：chest、headache、abdomen 或 other，不要有其他文字。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=5,
        )
        route = result.strip().lower().strip("`'\".。 ")
        if route in ("chest", "headache", "abdomen", "other"):
            return route
        raise ValueError(f"無效的分流輸出：{route[:20]}")
    except Exception as e:
        traceback.print_exc()
        print(f"[Classify] LLM 分流失敗，改用關鍵字判斷: {e}")
        if matched:
            return matched[0]
        return "other"


def parse_gender(text: str) -> str | None:
    raw = text.strip()
    corrected = correct_transcription(text)

    if corrected.startswith("其他：") and corrected[3:].strip():
        return corrected
    if any(w in corrected for w in ["男性", "男生", "先生", "男"]):
        return "男"
    if any(w in corrected for w in ["女性", "女生", "小姐", "女"]):
        return "女"

    if any(w in raw for w in FEMALE_SOUNDALIKES):
        return "女"
    if any(w in raw for w in MALE_SOUNDALIKES):
        return "男"

    return None


def parse_onset(text: str) -> tuple[str, str] | None:
    text = correct_transcription(text)
    return parse_onset_answer(text)


def build_summary(data: dict, *, include_identity: bool = True) -> str:
    ctype = data.get("type", "chest")
    default_reason = {"chest": "胸痛", "headache": "頭痛", "abdomen": "腹痛"}.get(ctype, "胸痛")

    identity_line = (
        f"- 姓名：{data.get('name', '未提供')}\n"
        f"- 出生日期：{data.get('birth_date', '未提供')}\n"
        if include_identity
        else ""
    )
    base = f"""患者基本資料：
{identity_line}- 性別：{data.get('gender', '未提供')}
- 年齡：{data.get('age', '未提供')}歲
- 血型：{data.get('blood_type', '未提供')}
- 就診原因：{data.get('reason', default_reason)}
"""

    if ctype == "headache":
        symptom_block = f"""
頭痛問卷：
- 發作時間：{data.get('onset_num', '?')} {data.get('onset_unit', '')}
- 發作方式：{data.get('start_type', '未填')}
- 疼痛位置：{data.get('location', '未填')}
- 是否此生最痛一次：{data.get('worst_ever', '未填')}
- 疼痛性質：{data.get('quality', '未填')}
- 加重因素：{data.get('aggravate', '未填')}
- 緩解因素：{data.get('relieve', '未填')}
- 伴隨症狀：{data.get('associated', '未填')}
- 危險因子（外傷／免疫低下／抗凝血劑／懷孕產後）：{data.get('risk_flags', '未填')}

病史：
- 抽菸：{data.get('smoke', '未填')}
- 神經血管疾病史：{data.get('neuro', '未填')}"""
    elif ctype == "abdomen":
        symptom_block = f"""
腹痛問卷：
- 發作時間：{data.get('onset_num', '?')} {data.get('onset_unit', '')}
- 疼痛性質：{data.get('quality', '未填')}
- 疼痛位置：{data.get('location', '未填')}
- 伴隨症狀：{data.get('associated', '未填')}
- 家人/同行是否有相同症狀：{data.get('contact_history', '未填')}

病史：
- 抽菸：{data.get('smoke', '未填')}
- 腹部相關病史：{data.get('abdomen_hx', '未填')}"""
    else:
        symptom_block = f"""
胸痛問卷：
- 發作時間：{data.get('onset_num', '?')} {data.get('onset_unit', '')}
- 發作方式：{data.get('start_type', '未填')}
- 疼痛位置：{data.get('location', '未填')}
- 痛點型態：{data.get('fixed', '未填')}
- 壓痛：{data.get('tender', '未填')}
- 疼痛性質：{data.get('quality', '未填')}
- 加重因素：{data.get('aggravate', '未填')}
- 緩解因素：{data.get('relieve', '未填')}
- 伴隨症狀：{data.get('associated', '未填')}

病史：
- 抽菸：{data.get('smoke', '未填')}
- 心肺疾病史：{data.get('cardio', '未填')}"""

    tail = f"""
- 慢性疾病：{data.get('chronic', '未填')}{' (' + data['chronic_detail'] + ')' if data.get('chronic_detail') else ''}
- 過去藥物治療：{data.get('past_meds', '未填')}
- 手術史：{data.get('surgery', '未填')}{' (' + data['surgery_detail'] + ')' if data.get('surgery_detail') else ''}
- 目前用藥：{data.get('current_meds', '沒有')}
- 過敏史：{data.get('allergy', '沒有')}
"""

    return (base + symptom_block + tail).strip()


def clinical_patient_data(data: dict | None) -> dict:
    """檢索與外部模型不需要直接識別資訊，只保留臨床欄位。"""
    identity_fields = {
        "name",
        "birth_date",
        "national_id",
        "id_number",
        "patient_id",
    }
    return {
        key: value
        for key, value in (data or {}).items()
        if key not in identity_fields
    }


def model_patient_summary(record: dict) -> str:
    """提供給外部模型的摘要，刻意排除姓名與出生日期。"""
    return build_summary(
        clinical_patient_data(record.get("data")),
        include_identity=False,
    )


# ── 測試用假病人（問診編號 00000）──────────────────────────
# 純粹為了開發/測試方便：每次重啟後端，都會自動在 patient_records
# 建立這筆假資料，醫師端直接輸入 00000 就能載入，不用每次都重新跑一次
# 病患端完整問卷。內容是寫死的胸痛案例，AI 初步評估也是寫死文字
# （不會呼叫 LLM），報告內文明確標註「測試用假病人資料」，
# 避免被誤認為真實模型生成的評估結果。
TEST_PATIENT_QUEUE_NUMBER = "00000"


def _seed_test_patient():
    if TEST_PATIENT_QUEUE_NUMBER in patient_records:
        return

    test_data = {
        "type": "chest",
        "gender": "男",
        "age": "52",
        "reason": "胸痛",
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

    fake_report = (
        "【基本資料】\n男性／52歲\n\n"
        "【主訴】\n30分鐘前突然發作的左側胸痛，痛點固定，感覺有重物壓迫\n\n"
        "【伴隨症狀】\n冒冷汗、心跳加速或不規則\n\n"
        "【過去病史】\n高血壓，過去有抽菸但已戒菸，未曾手術，目前無用藥\n\n"
        "【初步評估】\n（測試資料：此份AI初步評估為預先寫死內容，非實際模型生成，僅供介面測試用）\n\n"
        "【建議】\n建議立即就醫評估，排除急性冠心症候群等致命病因。\n\n"
        "※ 此為測試用假病人資料（問診編號 00000），非真實病人，僅供醫師端介面測試使用。"
    )

    patient_records[TEST_PATIENT_QUEUE_NUMBER] = {
        "queue_number": TEST_PATIENT_QUEUE_NUMBER,
        "type": "chest",
        "reason": test_data["reason"],
        "summary": build_summary(test_data),
        "report": fake_report,
        "data": test_data,
        "ts": time.time(),
    }
    print(f"[Seed] 已建立測試病人，問診編號：{TEST_PATIENT_QUEUE_NUMBER}")


_seed_test_patient()


def build_report_prompt(data: dict) -> str:
    ctype = data.get("type", "chest")
    # 姓名不影響臨床摘要，不送給外部 LLM；出生日期只保留計算後年齡。
    report_data = clinical_patient_data(data)
    summary = build_summary(report_data, include_identity=False)
    chief_label = {"chest": "胸痛", "headache": "頭痛", "abdomen": "腹痛"}.get(ctype, "胸痛")

    rag_context = ""
    danger_context = ""
    if RAG_ENABLED:
        try:
            rag_context = build_context(report_data, ctype)
            print(f"[RAG] build_context 撈到 {len(rag_context)} 字的內容")
        except Exception as e:
            print(f"[RAG] build_context 查詢失敗: {e}")

        try:
            danger_query = f"{data.get('reason', '')} {data.get('associated', '')} 危險徵兆 紅旗症狀 鑑別診斷".strip()
            danger_context, _ = retrieve_context_block(
                danger_query,
                n_results=4,
                primary_route=ctype,
                patient_data=report_data,
                purpose="diagnosis",
            )
            print("[RAG] 已完成補充危險徵兆檢索")
        except Exception as e:
            print(f"[RAG] 補充危險徵兆檢索失敗: {e}")
            danger_context = ""

    context_parts = []
    if rag_context:
        context_parts.append(rag_context)
    if danger_context and danger_context != "（知識庫中查無相關內容）":
        context_parts.append(f"【針對本次主訴與伴隨症狀額外檢索的危險徵兆／鑑別診斷內容】\n{danger_context}")

    if context_parts:
        combined = "\n\n".join(context_parts)
        context_block = f"""
以下是從 Medscape 醫學文獻庫（Emergency Medicine / Infectious Diseases / Laboratory Medicine）擷取的相關醫學知識，請務必參考並引用於評估中；若有多段內容，請優先引用跟本次主訴、伴隨症狀最相關的部分：

{combined}

---
"""
    else:
        context_block = ""

    return f"""
你是一位資深急診醫師，正在審閱預問診資料並撰寫臨床評估摘要。
請用繁體中文、真實醫師的口吻回答。絕對不可做正式診斷。

{context_block}
以下是病患的預問診資料：

{summary}

請輸出以下格式的評估摘要：

【基本資料】
性別／年齡

【主訴】
{chief_label}發作狀況（時間、位置、性質）

【伴隨症狀】
列出重要伴隨症狀

【過去病史】
慢性病、手術、用藥史

【初步評估】
請直接引用上方醫學知識庫中的相關內容，說明需要特別注意的鑑別診斷方向（2～3句）。
若知識庫有提到具體的危險徵兆或診斷標準，請明確帶入，不要只說通用知識。

【建議】
一句話建議（是否需要立即就醫或可觀察）

限制：
- 總長不超過350字
- 語氣像真人醫生，不過度正式
- 初步評估必須引用 RAG 知識庫的具體內容
- 絕對不做正式診斷
"""


class DoctorChatRequest(BaseModel):
    message: str = ""
    session_id: str
    mode: str = "chat"  # "chat"：一般文獻問答 / "structured_note"：口語主訴→六段式結構化病歷+臨床決策

    @validator("session_id")
    def session_id_not_empty(cls, v):
        if not v.strip():
            raise ValueError("session_id 不可為空")
        return v.strip()[:64]

    @validator("message")
    def message_length(cls, v):
        return v.strip()[:1000]

    @validator("mode")
    def mode_valid(cls, v):
        v = (v or "chat").strip().lower()
        return v if v in ("chat", "structured_note") else "chat"


class LoadPatientRequest(BaseModel):
    session_id: str
    queue_number: str

    @validator("session_id")
    def session_id_not_empty(cls, v):
        if not v.strip():
            raise ValueError("session_id 不可為空")
        return v.strip()[:64]

    @validator("queue_number")
    def queue_number_format(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("問診編號不可為空")
        return v[:16]


def _cleanup_doctor_sessions():
    now = time.time()
    expired = [sid for sid, s in doctor_sessions.items() if now - s.get("ts", 0) > DOCTOR_SESSION_TTL]
    for sid in expired:
        del doctor_sessions[sid]


DOCTOR_SYSTEM_PROMPT = (
    "你是提供實證醫學文獻查詢的 AI 助手，服務對象是急診醫師。"
    "請用繁體中文、專業但精簡的口吻回答，可使用醫學術語。"
    "回答時請務必根據下方提供的『醫學知識庫內容』作答，"
    "若知識庫內容不足以回答，請明確告知醫師「知識庫未涵蓋此問題」，"
    "不要編造未經查證的醫學資訊。"
    "若對話中有提供『目前正在討論的病人』資料，請優先針對這位病人的實際狀況分析回答，"
    "而不是給通用衛教答案。"
    "回答結尾請簡短列出參考的文章標題（不需要完整網址）。"
)

STRUCTURED_NOTE_SYSTEM_PROMPT = (
    "你是資深急診醫師的臨床決策輔助助手，服務對象是第一線護理師／醫師。"
    "對方會用口語、零碎的方式描述病人主訴，你要把它轉成標準化病歷，"
    "並提供結構化的臨床決策建議，協助醫師在忙碌中不漏掉致命診斷。"
    "請務必依照使用者提供的六個段落標題與順序輸出，不要增減段落、不要更改標題文字。"
    "所有內容以繁體中文撰寫。"
    "第3、5、6段請務必具體引用『醫學知識庫內容』的實際依據（例如危險徵兆、診斷標準、"
    "建議檢查項目），不要只給通用衛教式建議；若知識庫內容不足以支持某段，"
    "請註明「此段建議請依臨床判斷」，不要編造未經查證的醫學資訊。"
    "全程僅供臨床決策參考，不做正式診斷，最終判斷仍以主治醫師之理學檢查與檢驗結果為準。"
)


def build_structured_note_prompt(
    complaint_text: str,
    patient: dict | None,
    diag_context: str,
    lab_context: str,
    imaging_context: str,
) -> str:
    patient_block = ""
    if patient:
        patient_block = f"""此病人已完成AI預問診問卷，既有資料如下，請一併納入分析：

{model_patient_summary(patient)}

【問診端AI初步評估】
{patient['report']}

---

"""

    return f"""{patient_block}醫護人員剛剛輸入的口語主訴／補充資訊：
{complaint_text}

---

以下是分別針對不同面向檢索出的醫學知識庫內容，請在對應段落具體引用：

【醫學知識庫 A：鑑別診斷／危險徵兆相關】（撰寫「初步鑑別診斷」「防漏診鑑別」時請具體引用）
{diag_context}

【醫學知識庫 B：檢驗（抽血／驗尿）相關】（撰寫「檢驗建議」時請具體引用）
{lab_context}

【醫學知識庫 C：影像學相關】（撰寫「影像學決策」時請具體引用）
{imaging_context}

---

請嚴格依照以下六個段落標題與順序輸出（標題請完全照抄，不要翻譯或合併）：

【病歷摘要 EMR】
CC（主訴）：
PI（現病史）：
PH（過去病史）：
Meds（用藥）：
Allergy（過敏史）：

【初步鑑別診斷（前3項最可能）】
1.
2.
3.
（每項附一行簡短理由）

【防漏診鑑別 — 5個絕對不能漏掉的隱形殺手】
1.
2.
3.
4.
5.
（每項須是致命或有嚴重併發症風險的鑑別診斷，並簡述為何不能漏掉；請引用醫學知識庫A中的具體危險徵兆或診斷標準）

【理學檢查建議】
（列出2～4項，最低成本、床邊可立即執行的理學檢查重點，並說明要觀察什麼）

【檢驗建議（抽血／驗尿）】
（只列出有鑑別力、真正需要的項目，避免不必要的過度檢查，並簡述每項要排除或確認什麼；請引用醫學知識庫B）

【影像學決策】
（先列基礎影像如X-ray/Echo；若建議CT或MRI，必須額外用1～2句說明「為什麼此案例必須做，而非常規基礎影像可取代」；請引用醫學知識庫C）

限制：
- 語氣專業精簡，像資深主治醫師跟住院醫師交班
- 若某個知識庫內容與病情不相關或查無內容，該段請註明「此段建議請依臨床判斷」，不要編造
- 不做正式診斷，僅供臨床決策參考
"""


@app.get("/health")
def health():
    current_rag_status = (
        get_rag_status() if "get_rag_status" in globals() else RAG_STATUS
    )
    return {
        "status": "ok",
        "llm_provider": llm_client.provider,
        "llm_model": llm_client.model,
        "sessions": len(sessions),
        "doctor_sessions": len(doctor_sessions),
        "rag_enabled": current_rag_status["enabled"],
        "rag_index_version": current_rag_status["index_version"],
        "rag_collections": current_rag_status["collections"],
        "rag_legacy_available": current_rag_status["legacy_available"],
        "rag_query_translation": current_rag_status.get(
            "query_translation",
            {
                "enabled": False,
                "provider": "off",
                "query_mode": "dual",
                "model": "",
            },
        ),
    }


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not audio.content_type or "audio" not in audio.content_type:
        raise HTTPException(status_code=400, detail="請上傳音訊檔案")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音訊檔案過大（上限 10MB）")

    try:
        raw_text = llm_client.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            mime_type=audio.content_type,
            prompt=WHISPER_PROMPT,
        )
        corrected_text = correct_transcription(raw_text)

        print(f"[Transcribe:{llm_client.provider}] 原始: {raw_text}")
        print(f"[Transcribe:{llm_client.provider}] 修正: {corrected_text}")

        return {"text": corrected_text}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"語音辨識失敗：{str(e)}")


def _question_payload(
    session: dict,
    *,
    reply: str,
    user_display=None,
    completed: bool = False,
    queue_number: str | None = None,
) -> dict:
    questionnaire = session.get("questionnaire", CHIEF_QUESTIONNAIRE)
    index = session.get("index", 0)
    data = session.get("data", {})
    current = (
        questionnaire[index]
        if not completed and 0 <= index < len(questionnaire)
        else None
    )
    return {
        "reply": reply,
        "session_id": session["session_id"],
        "completed": completed,
        "user_display": user_display,
        "step": -1 if completed else index,
        "queue_number": queue_number,
        "question_input": (
            structured_question_input(current) if current else None
        ),
        "questionnaire": (
            questionnaire_meta(current, data.get("type"))
            if current
            else None
        ),
        "progress": (
            {"current": 1, "total": 1, "percent": 100}
            if completed
            else progress_meta(questionnaire, index, data)
        ),
    }


def _section_transition_reply(
    previous_section: str,
    current: dict,
    route: str,
    prefilled_fields: set[str] | None = None,
) -> str:
    prompt = current["prompt"]
    prefilled_fields = prefilled_fields or set()
    basic_fields = {"name", "gender", "birth_date", "blood_type"}
    history_fields = {
        "smoke",
        "chronic",
        "past_meds",
        "current_meds",
        "allergy",
    }
    if previous_section == current["section"]:
        return prompt
    if current["section"] == "basic":
        return f"主訴已記錄。接下來填寫基本資料。\n\n{prompt}"
    if current["section"] == "history":
        if basic_fields.issubset(prefilled_fields):
            return (
                "主訴已記錄，基本資料已從病歷帶入。"
                f"接下來補充尚未取得的病史。\n\n{prompt}"
            )
        return f"基本資料完成。接下來了解一般病史。\n\n{prompt}"
    if current["section"] == "disease":
        if basic_fields.issubset(prefilled_fields):
            imported = (
                "基本資料與病史"
                if history_fields.issubset(prefilled_fields)
                else "基本資料"
            )
            return (
                f"已從病歷帶入{imported}。接下來進入"
                f"{ROUTE_LABELS.get(route, '症狀')}問卷。\n\n{prompt}"
            )
        return (
            f"病史資料完成。接下來進入"
            f"{ROUTE_LABELS.get(route, '症狀')}問卷。\n\n{prompt}"
        )
    return prompt


async def _complete_consultation(session: dict, user_display: str) -> dict:
    data = session["data"]
    ctype = data["type"]
    try:
        ai_report = llm_client.generate_text(
            [
                {
                    "role": "system",
                    "content": (
                        "你是資深急診醫師。請用繁體中文、自然醫師口吻撰寫"
                        "預問診摘要。初步評估必須引用提供的醫學知識庫內容，"
                        "帶入具體的危險徵兆或診斷標準。絕對不可做正式診斷。"
                    ),
                },
                {"role": "user", "content": build_report_prompt(data)},
            ],
            temperature=0.3,
            max_tokens=600,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI 生成失敗：{str(e)}")

    _cleanup_patient_records()
    queue_number = generate_queue_number(ctype)
    patient_records[queue_number] = {
        "queue_number": queue_number,
        "type": ctype,
        "reason": data.get("reason", ""),
        "summary": build_summary(data),
        "report": ai_report,
        "data": data,
        "ts": time.time(),
    }
    session["step"] = -1
    session["index"] = -1
    reply = (
        f"謝謝您的回答，問診已完成。\n\n"
        f"────────────\n"
        f"📋 您的問診編號為：{queue_number}\n"
        f"────────────\n\n"
        "請您耐心等候叫號，輪到您的號碼時醫師會與您看診。"
        "如果您感到非常不舒服，請立即告知現場護理師。"
    )
    return _question_payload(
        session,
        reply=reply,
        user_display=user_display,
        completed=True,
        queue_number=queue_number,
    )


@app.post("/chat")
async def chat(req: ChatRequest):
    _cleanup_sessions()

    if req.session_id not in sessions:
        prefill = (
            req.patient_prefill.dict(exclude_none=True)
            if req.patient_prefill
            else {}
        )
        prefill.pop("source", None)
        data = {}
        prefilled_fields = set()
        for field, value in prefill.items():
            if not value:
                continue
            if field == "birth_date":
                parsed_birth_date = parse_birth_date(value)
                if parsed_birth_date is None:
                    continue
                data["birth_date"], age = parsed_birth_date
                data["age"] = str(age)
            elif field == "gender":
                data[field] = parse_gender(value) or value
            else:
                data[field] = value
            prefilled_fields.add(field)

        session = {
            "session_id": req.session_id,
            "step": 0,
            "index": 0,
            "questionnaire": list(CHIEF_QUESTIONNAIRE),
            "data": data,
            "prefilled_fields": list(prefilled_fields),
            "ts": time.time(),
        }
        sessions[req.session_id] = session
        return _question_payload(
            session,
            reply=(
                "您好！我是您的數位醫療助理。請先說明主訴，"
                "之後會依序填寫基本資料、病史與症狀問卷。\n\n"
                f"{CHIEF_QUESTIONNAIRE[0]['prompt']}"
            ),
        )

    session = sessions[req.session_id]
    session["ts"] = time.time()
    if session.get("index") == -1:
        return _question_payload(
            session,
            reply="本次預問診已完成，請重新整理頁面開始新的問診。",
            user_display=req.message or None,
            completed=True,
        )

    questionnaire = session["questionnaire"]
    index = session["index"]
    current = questionnaire[index]
    data = session["data"]
    user_input = req.message.strip()

    if not user_input:
        return _question_payload(
            session,
            reply=f"請輸入內容後再送出。\n\n{current['prompt']}",
        )
    if is_junk(user_input):
        return _question_payload(
            session,
            reply=f"抱歉，我沒有聽清楚，請再回答一次。\n\n{current['prompt']}",
        )

    field = current["field"]
    user_display = user_input

    if field == "reason":
        data["reason"] = user_input
        route = classify_complaint(user_input)
        data["type"] = route
        print(f"[Classify] 主訴路由 → {route}")
        if route not in ("chest", "headache", "abdomen"):
            session["step"] = -1
            session["index"] = -1
            return _question_payload(
                session,
                reply=(
                    "了解，您描述的症狀目前不在胸痛／頭痛／腹痛問診"
                    "範圍內，建議直接由現場護理師或醫師進一步分流。"
                ),
                user_display=user_display,
                completed=True,
            )
        questionnaire = build_questionnaire(route)
        session["questionnaire"] = questionnaire
    elif field == "gender":
        gender = parse_gender(user_input)
        if gender is None and user_input != "不便透露":
            return _question_payload(
                session,
                reply=f"無法辨識此選項，請重新選擇。\n\n{current['prompt']}",
            )
        data[field] = gender or user_input
        user_display = {
            "男": "男性",
            "女": "女性",
        }.get(data[field], data[field])
    elif field == "birth_date":
        parsed_birth_date = parse_birth_date(user_input)
        if parsed_birth_date is None:
            return _question_payload(
                session,
                reply=(
                    "出生日期格式不正確或超出合理範圍，請重新選擇。"
                    f"\n\n{current['prompt']}"
                ),
            )
        data["birth_date"], age = parsed_birth_date
        data["age"] = str(age)
        user_display = data["birth_date"]
    elif field == "onset":
        parsed_onset = parse_onset(user_input)
        if parsed_onset is None:
            return _question_payload(
                session,
                reply=(
                    "我無法確定時間長度，請同時輸入數字和單位，"
                    "例如「30分鐘前」或「1個月前」。"
                ),
            )
        data["onset_num"], data["onset_unit"] = parsed_onset
        data["onset"] = user_input
        user_display = (
            f"{data['onset_num']} {data['onset_unit']}".strip()
        )
    else:
        if field == "location" and req.pain_location_ids:
            pain_locations = serialize_pain_locations(req.pain_location_ids)
            data["pain_locations"] = pain_locations
            user_input = "、".join(
                location["label"] for location in pain_locations
            )
            user_display = user_input
        data[field] = user_input

    prefilled_fields = set(session.get("prefilled_fields", []))
    next_index = next_question_index(
        questionnaire,
        index,
        data,
        skip_fields=prefilled_fields,
    )
    if next_index is None:
        return await _complete_consultation(session, user_display)

    previous_section = current["section"]
    session["index"] = next_index
    session["step"] = next_index
    next_question = questionnaire[next_index]
    return _question_payload(
        session,
        reply=_section_transition_reply(
            previous_section,
            next_question,
            data["type"],
            prefilled_fields,
        ),
        user_display=user_display,
    )


def retrieve_context_block(
    query: str,
    n_results: int = 6,
    primary_route: str | None = None,
    patient_data: dict | None = None,
    purpose: str = "general",
) -> tuple[str, list[dict]]:
    """
    執行一次 RAG 檢索，回傳 (整理好的知識庫文字, 來源清單)。
    """
    try:
        chunks = retrieve(
            query,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose=purpose,
            final_k=n_results,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"向量庫查詢失敗：{str(e)}")

    title_counts = {}
    context_parts = []
    sources = []
    for chunk in chunks:
        title = chunk["title"]
        if title_counts.get(title, 0) >= 2:
            continue
        title_counts[title] = title_counts.get(title, 0) + 1
        context_parts.append(f"[{chunk['source']} — {title}]\n{chunk['text'][:900]}")
        sources.append({
            "title": title,
            "source": chunk["source"],
            "url": chunk.get("url", ""),
            "route": chunk.get("route", ""),
        })

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "（知識庫中查無相關內容）"
    return context_block, sources


def _dedup_sources(*source_lists: list[dict]) -> list[dict]:
    seen = set()
    merged = []
    for sources in source_lists:
        for s in sources:
            if s["title"] not in seen:
                seen.add(s["title"])
                merged.append(s)
    return merged


def _generate_structured_note_for_patient(record: dict) -> tuple[str | None, list[dict]]:
    """
    針對已完成問診的病人，自動用他的主訴／問卷摘要／AI初步評估
    產生六段式結構化病歷＋臨床決策分析。
    供 /doctor/load_patient 在載入病人當下自動呼叫，
    醫師不需要再手動輸入或切換模式。
    """
    if not RAG_ENABLED:
        return None, []

    base_query = record.get("reason", "")
    primary_route = record.get("type")
    patient_data = clinical_patient_data(record.get("data"))

    try:
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀",
            n_results=5,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="diagnosis",
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="lab",
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="imaging",
        )
        sources = _dedup_sources(diag_sources, lab_sources, imaging_sources)

        complaint_text = (
            f"病人主訴：{base_query}。詳細問卷內容與AI初步評估請見上方提供的病人資料，"
            "請直接根據該資料進行完整的結構化分析。"
        )

        user_prompt = build_structured_note_prompt(
            complaint_text=complaint_text,
            patient=record,
            diag_context=diag_context,
            lab_context=lab_context,
            imaging_context=imaging_context,
        )

        structured_note = llm_client.generate_text(
            [
                {"role": "system", "content": STRUCTURED_NOTE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        return structured_note, sources

    except Exception as e:
        traceback.print_exc()
        print(f"[LoadPatient] 自動產生結構化病歷失敗: {e}")
        return None, []


# ── 醫師端 RAG 聊天 ─────────────────────────────────────
@app.post("/doctor/load_patient")
def load_patient(req: LoadPatientRequest):
    """
    醫師輸入問診編號，載入該病人的問卷摘要＋AI初步評估報告，
    並「自動」產生六段式結構化病歷＋臨床決策分析（CC/PI/PH/Meds/Allergy、
    初步鑑別診斷、防漏診鑑別、理學檢查建議、檢驗建議、影像學決策），
    醫師不需要再手動輸入任何文字或切換模式。
    之後同一個 session 內的 /doctor/chat 都會自動帶入這位病人的背景資料，
    可繼續追問細節。
    """
    _cleanup_patient_records()

    record = patient_records.get(req.queue_number)
    if not record:
        raise HTTPException(status_code=404, detail="查無此問診編號，請確認編號是否正確或已過期")

    if req.session_id not in doctor_sessions:
        doctor_sessions[req.session_id] = {"history": [], "ts": time.time(), "patient": None}

    dsession = doctor_sessions[req.session_id]
    dsession["ts"] = time.time()
    dsession["patient"] = record
    dsession["history"] = []  # 換病人時清空對話歷史，避免混淆

    structured_note, structured_sources = _generate_structured_note_for_patient(record)

    if structured_note:
        # 把自動產生的分析存進對話歷史，讓醫師之後在同一 session 繼續追問時，
        # AI 還記得這份分析內容，不用重講一次病人狀況。
        dsession["history"].append({
            "user": "（系統自動）載入病人後請提供六段式結構化病歷分析",
            "assistant": structured_note,
        })

    return {
        "queue_number": record["queue_number"],
        "type": record["type"],
        "reason": record["reason"],
        "summary": record["summary"],
        "report": record["report"],
        "structured_note": structured_note,
        "structured_sources": structured_sources,
        "pain_locations": record.get("data", {}).get("pain_locations", []),
        "rag_enabled": RAG_ENABLED,
    }


@app.delete("/doctor/patient/{session_id}")
def unload_patient(session_id: str):
    """醫師端取消目前載入的病人（回到一般文獻查詢模式）"""
    if session_id in doctor_sessions:
        doctor_sessions[session_id]["patient"] = None
        doctor_sessions[session_id]["history"] = []
    return {"status": "ok"}


@app.post("/doctor/chat")
async def doctor_chat(req: DoctorChatRequest):
    """
    醫師端自由問答，根據 Medscape 向量庫（RAG）回答臨床/文獻問題。
    支援多輪對話（同一 session_id 內會記住歷史）。
    若該 session 已透過 /doctor/load_patient 載入病人，會自動把病人資料當背景。
    也可手動切換 mode="structured_note"，針對新輸入的口語主訴（例如追加的補充資訊）
    再產生一次新的六段式分析。
    """
    _cleanup_doctor_sessions()

    if not req.message:
        raise HTTPException(status_code=400, detail="請輸入問題內容")

    if req.session_id not in doctor_sessions:
        doctor_sessions[req.session_id] = {"history": [], "ts": time.time(), "patient": None}

    dsession = doctor_sessions[req.session_id]
    dsession["ts"] = time.time()
    patient = dsession.get("patient")

    if not RAG_ENABLED:
        raise HTTPException(status_code=503, detail="RAG 向量庫尚未建立，請先執行 ingest.py")

    base_query = req.message
    if patient:
        base_query = f"{req.message} {patient.get('reason', '')}"

    if req.mode == "structured_note":
        primary_route = patient.get("type") if patient else None
        patient_data = (
            clinical_patient_data(patient.get("data"))
            if patient
            else None
        )
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀",
            n_results=5,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="diagnosis",
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="lab",
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波",
            n_results=4,
            primary_route=primary_route,
            patient_data=patient_data,
            purpose="imaging",
        )
        sources = _dedup_sources(diag_sources, lab_sources, imaging_sources)
    else:
        context_block, sources = retrieve_context_block(
            base_query,
            n_results=6,
            primary_route=patient.get("type") if patient else None,
            patient_data=(
                clinical_patient_data(patient.get("data"))
                if patient
                else None
            ),
            purpose="general",
        )

    patient_block = ""
    if patient:
        patient_block = f"""目前正在討論的病人：

{model_patient_summary(patient)}

【AI初步評估】
{patient['report']}

---

"""

    if req.mode == "structured_note":
        user_prompt = build_structured_note_prompt(
            req.message, patient, diag_context, lab_context, imaging_context
        )
        messages = [
            {"role": "system", "content": STRUCTURED_NOTE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        max_tokens = 1400
    else:
        messages = [{"role": "system", "content": DOCTOR_SYSTEM_PROMPT}]
        for turn in dsession["history"][-DOCTOR_HISTORY_MAX_TURNS:]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})

        user_prompt = f"""{patient_block}醫學知識庫內容：

{context_block}

---

醫師的問題：{req.message}"""
        messages.append({"role": "user", "content": user_prompt})
        max_tokens = 800

    try:
        reply = llm_client.generate_text(
            messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI 生成失敗：{str(e)}")

    dsession["history"].append({"user": req.message, "assistant": reply})
    if len(dsession["history"]) > DOCTOR_HISTORY_MAX_TURNS:
        dsession["history"] = dsession["history"][-DOCTOR_HISTORY_MAX_TURNS:]

    return {
        "reply": reply,
        "session_id": req.session_id,
        "sources": sources,
        "patient_loaded": patient["queue_number"] if patient else None,
        "mode": req.mode,
    }


@app.delete("/doctor/session/{session_id}")
def doctor_reset(session_id: str):
    doctor_sessions.pop(session_id, None)
    return {"status": "ok", "cleared": session_id}
