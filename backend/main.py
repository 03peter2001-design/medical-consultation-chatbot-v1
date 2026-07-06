from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from groq import Groq
from dotenv import load_dotenv
import os
import re
import time
import random
import traceback

load_dotenv()

app = FastAPI(title="AI 預問診系統", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("缺少環境變數 GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

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
try:
    from rag import build_context, retrieve, _get_collection
    import os as _os

    _BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
    _CHROMA_DIR = _os.path.join(_BASE_DIR, "chroma_db")

    if _os.path.exists(_CHROMA_DIR):
        _get_collection()
        RAG_ENABLED = True
        print("[RAG] 向量庫已載入，RAG 功能啟用")
    else:
        print(f"[RAG] 未找到 chroma_db（{_CHROMA_DIR}），請先執行 python ingest.py（RAG 停用）")
except ImportError:
    print("[RAG] rag.py 未找到，RAG 停用")

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


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str

    @validator("session_id")
    def session_id_not_empty(cls, v):
        if not v.strip():
            raise ValueError("session_id 不可為空")
        return v.strip()[:64]

    @validator("message")
    def message_length(cls, v):
        return v.strip()[:500]


STEPS_CHEST = {
    0: "init", 1: "reason", 2: "gender", 3: "age", 4: "onset_num", 5: "onset_unit",
    6: "start_type", 7: "location", 8: "fixed", 9: "tender", 10: "quality",
    11: "aggravate", 12: "relieve", 13: "associated", 14: "smoke", 15: "cardio",
    16: "chronic", 17: "chronic_detail", 18: "past_meds", 19: "surgery",
    20: "surgery_detail", 21: "current_meds", 22: "allergy", 23: "report",
}

STEPS_HEADACHE = {
    0: "init", 1: "reason", 2: "gender", 3: "age", 4: "onset_num", 5: "onset_unit",
    6: "start_type", 7: "location", 8: "worst_ever", 9: "quality", 10: "aggravate",
    11: "relieve", 12: "associated", 13: "risk_flags", 14: "smoke", 15: "neuro",
    16: "chronic", 17: "chronic_detail", 18: "past_meds", 19: "surgery",
    20: "surgery_detail", 21: "current_meds", 22: "allergy", 23: "report",
}

STEPS_ABDOMEN = {
    0: "init", 1: "reason", 2: "gender", 3: "age", 4: "onset_num", 5: "onset_unit",
    6: "quality", 7: "location", 8: "associated", 9: "contact_history",
    14: "smoke", 15: "abdomen_hx", 16: "chronic", 17: "chronic_detail",
    18: "past_meds", 19: "surgery", 20: "surgery_detail", 21: "current_meds",
    22: "allergy", 23: "report",
}

CHEST_KEYWORDS = ["胸痛", "胸悶", "胸緊", "胸壓", "胸口痛", "心口", "前胸", "胸部不適"]
HEADACHE_KEYWORDS = ["頭痛", "頭很痛", "頭暈痛", "偏頭痛", "頭脹", "頭部不適", "腦袋痛"]
ABDOMEN_KEYWORDS = ["肚子痛", "腹痛", "肚子不舒服", "腹部疼痛", "肚臍痛", "腹脹痛", "肚子", "胃痛"]

COMMON_QUESTIONS = {
    14: "平時是否有抽菸習慣，還是過去曾抽但已戒菸呢？（有，目前仍在抽 / 沒有，從未抽菸 / 過去有抽，但已戒菸）",
    16: "過去是否有下列慢性疾病史？（可複選，以逗號分隔）\n選項：糖尿病、慢性腎病、高血脂、肝硬化、自體免疫疾病、癌症、其他、以上皆無\n如果得過自體免疫疾病或癌症，請說出具體病名。",
    17: "您提到了需要進一步說明的疾病，請簡單描述一下（病名）。",
    18: "之前是否曾接受過以下藥物治療？（可複選，以逗號分隔）\n選項：抗組織胺、腎上腺素、類固醇、以上皆無",
    20: "您提到了其他手術，請簡單說明手術名稱。",
    21: "目前是否有正在服用的藥物？若有，請告知藥物名稱。（沒有 / 有，請填寫藥物名稱）",
    22: "是否有特殊藥物和食物過敏？若有，請描述對哪些特殊藥物或食物過敏。（沒有 / 有，請描述）",
}

CHEST_QUESTIONS = {
    4: "胸痛從什麼時候開始的？（例如：30分鐘前、2小時前、3天前）",
    5: "",
    6: "胸痛是突然發作，還是逐漸發作的呢？（突然發作 / 逐漸發作）",
    7: "胸痛的位置在哪裡？左邊、右邊、正中間，還是兩側都有呢？",
    8: "胸痛的位置是否會移動？（痛點固定 / 痛點會移動）",
    9: "是否有觸痛點？也就是用手按壓那個部位時，會不會有壓痛感？（有 / 沒有）",
    10: "你會如何描述這種疼痛？（可複選，以逗號分隔）\n選項：刺痛、鈍痛、感覺有重物壓迫",
    11: "你有觀察到哪些情況會使疼痛加重嗎？（可複選，以逗號分隔）\n選項：深呼吸、耗費體力的活動、感到有壓力的時候",
    12: "你有觀察到什麼情況能緩解疼痛嗎？（可複選，以逗號分隔）\n選項：休息、用藥、坐姿、按摩疼痛部位",
    13: "請幫我觀察是否出現以下症狀，並將有出現的症狀告訴我：（可複選，以逗號分隔）\n選項：感到呼吸急促、冒冷汗、感到噁心或已經嘔吐、有昏厥要暈倒或頭暈的經歷、感到心跳加速或心跳不規則、咳嗽有痰、肚子痛\n（若都沒有請說「以上皆無」）",
    15: "過去是否有下列心肺疾病，並將過去有的心肺疾病描述給我聽：（可複選，以逗號分隔）\n選項：高血壓、心絞痛、心臟衰竭、心肌梗塞、心律不整、主動脈剝離、肺栓塞、肺高壓、心包膜積水、氣喘、肺癌、慢性阻塞型肺病、支氣管擴張、氣胸、中風\n（若都沒有請說「以上皆無」）",
    19: "是否接受過下列手術，並將過去有接受過的手術描述給我聽：（可複選，以逗號分隔）\n選項：心臟支架、心臟血管繞道手術、主動脈人工血管置換、主動脈支架、心律調節器、氣胸胸腔鏡手術、腦部手術、水腦引流、頸動脈手術、腦部放射線治療、頸椎手術、其他（請描述手術名稱）\n（若未曾手術請說「未曾手術」）",
}

HEADACHE_QUESTIONS = {
    4: "這次的頭痛，大概是從什麼時候開始的？（例如：30分鐘前、2小時前、3天前）",
    5: "",
    6: "這次的頭痛，是像被雷擊般在幾秒內就痛到最劇烈（爆炸性頭痛），還是慢慢加重的？（瞬間爆炸性 / 逐漸加重）",
    7: "頭痛的位置主要在哪裡？（單側 / 兩側都痛 / 前額 / 後腦勺及頸部 / 整個頭）",
    8: "這是您這輩子最嚴重、最劇烈的一次頭痛嗎？（是，前所未有的劇痛 / 不是，跟以前差不多或較輕）",
    9: "您會怎麼描述這個頭痛的感覺？（可複選，以逗號分隔）\n選項：像脈搏一樣的跳痛、悶脹痛、像被緊緊束住、針刺般的刺痛",
    10: "什麼情況下，頭痛會比較嚴重？（可複選，以逗號分隔）\n選項：咳嗽或用力、彎腰低頭、身體活動、光線刺激、聲音刺激",
    11: "什麼情況下，頭痛會比較緩解？（可複選，以逗號分隔）\n選項：休息、使用止痛藥、待在黑暗安靜的地方、按摩頭頸部",
    12: "除了頭痛，您還有以下哪些症狀？（可複選，以逗號分隔）\n選項：噁心或嘔吐、畏光、畏聲、視力模糊或複視、頸部僵硬合併發燒、單側肢體無力或麻木、講話不清楚、意識改變或嗜睡、以上皆無",
    13: "請問是否有以下情形？（可複選，以逗號分隔）\n選項：近期頭部外傷、癌症病史或免疫功能低下、目前服用抗凝血藥物、懷孕或產後六週內、以上皆無",
    15: "過去是否有以下神經血管相關疾病史？（可複選，以逗號分隔）\n選項：中風、腦動脈瘤、腦出血、腦膜炎或腦炎、腦部腫瘤、癲癇、偏頭痛病史、顳動脈炎、以上皆無",
    19: "過去是否曾接受過手術？（可複選，以逗號分隔）\n選項：腦部手術、腦動脈瘤夾閉或栓塞手術、水腦引流、頸動脈手術、腦部放射線治療、頸椎手術、其他、未曾手術",
}

ABDOMEN_QUESTIONS = {
    4: "肚子痛是從什麼時候開始的？（例如：30分鐘前、2小時前、3天前）",
    5: "",
    6: "請問肚子痛的性質為何？可以複選：（可複選，以逗號分隔）\n選項：鈍痛、刺痛、陣痛、持續痛、由前痛到背後、由肚臍周圍痛轉移到右下腹疼痛、飢餓時會加劇疼痛",
    7: "請問是肚子痛下列哪個位置？（可複選，以逗號分隔）\n選項：右上腹、左上腹、右下腹、左下腹、全腹痛、左側腰痛、右側腰痛、肚臍以下腹痛",
    8: "請問是否有下列合併症狀，可複選：（可複選，以逗號分隔）\n選項：腹瀉、發燒發冷、噁心、嘔吐、便秘、血便、冒冷汗、胃酸逆流、血尿、月經過期、陰道分泌物增加、呼吸道症狀、以上皆無",
    9: "是否有家中或是同行的人有相同的症狀？（是 / 否）",
    15: "請問你有過下列病史嗎？（可複選，以逗號分隔）\n選項：肝膽結石、腎結石、盲腸炎、腸阻塞、胰臟炎、腹主動脈瘤、紫質症、糖尿病酮酸中毒、以上皆無",
    19: "請問你有接受過下列腹部手術嗎？可以複選：（可複選，以逗號分隔）\n選項：剖腹產、闌尾切除、子宮切除、膽囊切除、大腸切除手術、胃切除手術、其他、未曾手術",
}


def get_steps_map(ctype: str) -> dict:
    if ctype == "headache":
        return STEPS_HEADACHE
    if ctype == "abdomen":
        return STEPS_ABDOMEN
    return STEPS_CHEST


INTRO_QUESTIONS = {
    0: "請問您的性別是？",
    1: "請問您的年齡是？",
    2: "請問您今天來看診，主要是哪裡不舒服呢？",
}


def get_question(step: int, ctype: str) -> str:
    if step in INTRO_QUESTIONS:
        return INTRO_QUESTIONS[step]
    if step in COMMON_QUESTIONS:
        return COMMON_QUESTIONS[step]
    src = HEADACHE_QUESTIONS if ctype == "headache" else (ABDOMEN_QUESTIONS if ctype == "abdomen" else CHEST_QUESTIONS)
    return src.get(step, "")


def is_chest_pain(text: str) -> bool:
    return any(kw in text for kw in CHEST_KEYWORDS)


def is_headache(text: str) -> bool:
    return any(kw in text for kw in HEADACHE_KEYWORDS)


def is_abdomen_pain(text: str) -> bool:
    return any(kw in text for kw in ABDOMEN_KEYWORDS)


def classify_complaint(text: str) -> str:
    hits = {
        "chest": is_chest_pain(text),
        "headache": is_headache(text),
        "abdomen": is_abdomen_pain(text),
    }
    matched = [k for k, v in hits.items() if v]

    if len(matched) == 1:
        return matched[0]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
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
        result = response.choices[0].message.content.strip().lower()
        if "chest" in result:
            return "chest"
        if "headache" in result:
            return "headache"
        if "abdomen" in result:
            return "abdomen"
        return "other"
    except Exception as e:
        traceback.print_exc()
        print(f"[Classify] LLM 分流失敗，改用關鍵字判斷: {e}")
        if matched:
            return matched[0]
        return "other"


def needs_chronic_detail(answer: str) -> bool:
    return any(t in answer for t in ["自體免疫疾病", "癌症", "其他"])


def needs_surgery_detail(answer: str) -> bool:
    return "其他" in answer


def parse_gender(text: str) -> str | None:
    raw = text.strip()
    corrected = correct_transcription(text)

    if any(w in corrected for w in ["男性", "男生", "先生", "男"]):
        return "男"
    if any(w in corrected for w in ["女性", "女生", "小姐", "女"]):
        return "女"

    if any(w in raw for w in FEMALE_SOUNDALIKES):
        return "女"
    if any(w in raw for w in MALE_SOUNDALIKES):
        return "男"

    return None


def parse_age(text: str) -> str | None:
    text = correct_transcription(text)
    numbers = re.findall(r"\d+", text)
    if numbers:
        age = int(numbers[0])
        if 0 < age < 130:
            return str(age)
    return None


def parse_onset(text: str) -> tuple[str, str]:
    text = correct_transcription(text)

    numbers = re.findall(r"\d+", text)
    num = numbers[0] if numbers else text

    if any(w in text for w in ["分鐘", "分"]):
        unit = "分鐘前"
    elif any(w in text for w in ["小時", "鐘頭"]):
        unit = "小時前"
    elif any(w in text for w in ["天", "日"]):
        unit = "天前"
    elif any(w in text for w in ["週", "周", "星期"]):
        unit = "週前"
    else:
        unit = "小時前"

    return num, unit


def next_step(current: int, data: dict, ctype: str = "chest") -> int:
    nxt = current + 1
    if nxt == 5:
        nxt = 6
    if ctype == "abdomen":
        if nxt in (10, 11, 12, 13):
            nxt = 14
    if nxt == 17 and not needs_chronic_detail(data.get("chronic", "")):
        nxt = 18
    if nxt == 20 and not needs_surgery_detail(data.get("surgery", "")):
        nxt = 21
    return nxt


def build_summary(data: dict) -> str:
    ctype = data.get("type", "chest")
    default_reason = {"chest": "胸痛", "headache": "頭痛", "abdomen": "腹痛"}.get(ctype, "胸痛")

    base = f"""患者基本資料：
- 性別：{data.get('gender', '未提供')}
- 年齡：{data.get('age', '未提供')}歲
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
    summary = build_summary(data)
    chief_label = {"chest": "胸痛", "headache": "頭痛", "abdomen": "腹痛"}.get(ctype, "胸痛")

    rag_context = ""
    danger_context = ""
    if RAG_ENABLED:
        try:
            rag_context = build_context(data, ctype)
            print(f"[RAG] build_context 撈到 {len(rag_context)} 字的內容")
        except Exception as e:
            print(f"[RAG] build_context 查詢失敗: {e}")

        try:
            danger_query = f"{data.get('reason', '')} {data.get('associated', '')} 危險徵兆 紅旗症狀 鑑別診斷".strip()
            danger_context, _ = retrieve_context_block(danger_query, n_results=4)
            print(f"[RAG] 補充危險徵兆檢索: {danger_query!r}")
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
        patient_block = f"""此病人已完成AI預問診問卷（問診編號 {patient['queue_number']}），既有資料如下，請一併納入分析：

{patient['summary']}

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
    return {
        "status": "ok",
        "sessions": len(sessions),
        "doctor_sessions": len(doctor_sessions),
        "rag_enabled": RAG_ENABLED,
    }


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not audio.content_type or "audio" not in audio.content_type:
        raise HTTPException(status_code=400, detail="請上傳音訊檔案")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音訊檔案過大（上限 10MB）")

    try:
        transcription = client.audio.transcriptions.create(
            file=(audio.filename or "audio.webm", audio_bytes),
            model="whisper-large-v3-turbo",
            language="zh",
            response_format="text",
            prompt=WHISPER_PROMPT,
        )
        raw_text = str(transcription).strip()
        corrected_text = correct_transcription(raw_text)

        print(f"[Whisper] 原始: {raw_text}")
        print(f"[Whisper] 修正: {corrected_text}")

        return {"text": corrected_text}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"語音辨識失敗：{str(e)}")


@app.post("/chat")
async def chat(req: ChatRequest):
    _cleanup_sessions()

    if req.session_id not in sessions:
        sessions[req.session_id] = {"step": 0, "data": {}, "ts": time.time()}
        return {
            "reply": "您好！我是您的數位醫療助理。在開始之前，先詢問您的基本資料。\n\n請問您的性別是？",
            "session_id": req.session_id,
            "completed": False,
            "user_display": None,
            "step": 0,
        }

    session = sessions[req.session_id]
    session["ts"] = time.time()
    step = session["step"]
    data = session["data"]
    user_input = req.message

    user_display = user_input if user_input else None

    if step == -1:
        return {
            "reply": "本次預問診已完成，請重新整理頁面開始新的問診。",
            "session_id": req.session_id,
            "completed": True,
            "user_display": user_display,
            "step": session["step"],
        }

    if not user_input:
        return {
            "reply": "請輸入內容後再送出。",
            "session_id": req.session_id,
            "completed": False,
            "user_display": None,
            "step": session["step"],
        }

    if is_junk(user_input):
        print(f"[Chat] Step {step} 收到雜訊，略過: {repr(user_input)}")
        current_q = get_question(step, data.get("type", "chest"))
        retry_hint = f"抱歉，我沒有聽清楚，請再說一次。\n\n{current_q}" if current_q else "抱歉，我沒有聽清楚，請再說一次。"
        return {
            "reply": retry_hint,
            "session_id": req.session_id,
            "completed": False,
            "user_display": None,
            "step": session["step"],
        }

    reply = ""
    completed = False
    queue_number = None

    if step == 0:
        gender = parse_gender(user_input)
        if gender is None:
            print(f"[Chat] Step 0 性別辨識失敗，原始輸入: {repr(user_input)}")
            return {
                "reply": "抱歉，我沒有聽清楚，請問您的性別是？",
                "session_id": req.session_id,
                "completed": False,
                "user_display": None,
                "step": session["step"],
            }
        data["gender"] = gender
        user_display = "男性" if gender == "男" else "女性"
        session["step"] = 1
        reply = "請問您的年齡是？"

    elif step == 1:
        age = parse_age(user_input)
        if age is None:
            print(f"[Chat] Step 1 年齡辨識失敗，原始輸入: {repr(user_input)}")
            return {
                "reply": "抱歉，我沒有聽清楚，請問您的年齡是？（請說出數字，例如：45）",
                "session_id": req.session_id,
                "completed": False,
                "user_display": None,
                "step": session["step"],
            }
        data["age"] = age
        session["step"] = 2
        reply = "請問您今天來看診，主要是哪裡不舒服呢？"

    elif step == 2:
        data["reason"] = user_input
        ctype = classify_complaint(user_input)
        data["type"] = ctype
        print(f"[Classify] 主訴「{user_input}」→ {ctype}")

        if ctype in ("chest", "headache", "abdomen"):
            session["step"] = 4
            label = {"chest": "胸痛", "headache": "頭痛", "abdomen": "腹痛"}[ctype]
            reply = f"了解，您說的是{label}的問題。\n\n{get_question(4, ctype)}"
        else:
            session["step"] = -1
            completed = True
            reply = (
                "了解，您描述的症狀目前不在胸痛／頭痛／腹痛問診範圍內，"
                "建議您直接前往門診掛號，讓醫師進一步評估。"
                "感謝您的配合，祝您早日康復！"
            )

    elif 4 <= step <= 22:
        ctype = data.get("type", "chest")
        key = get_steps_map(ctype)[step]
        if step == 4:
            data["onset_num"], data["onset_unit"] = parse_onset(user_input)
        else:
            data[key] = user_input

        nxt = next_step(step, data, ctype)

        if nxt <= 22:
            session["step"] = nxt
            if nxt == 6:
                q6 = get_question(6, ctype)
                reply = f"好的，{data.get('onset_num','')} {data.get('onset_unit','')}開始的。\n\n{q6}"
            elif nxt == 14:
                q14 = get_question(14, ctype)
                reply = f"好，接下來我想了解一些您的過去健康狀況。\n\n{q14}"
            elif nxt == 15 and ctype == "abdomen":
                q15 = get_question(15, ctype)
                reply = f"好，接下來我想了解一些您的過去健康狀況。\n\n{q15}"
            else:
                reply = get_question(nxt, ctype)
        else:
            session["step"] = -1
            completed = True
            try:
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": "你是資深急診醫師。請用繁體中文、自然醫師口吻撰寫預問診摘要。初步評估必須引用提供的醫學知識庫內容，帶入具體的危險徵兆或診斷標準。絕對不可做正式診斷。",
                        },
                        {"role": "user", "content": build_report_prompt(data)},
                    ],
                    temperature=0.3,
                    max_tokens=600,
                )
                ai_report = response.choices[0].message.content.strip()
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

            reply = (
                f"謝謝您的回答，問診已完成。\n\n"
                f"────────────\n"
                f"📋 您的問診編號為：{queue_number}\n"
                f"────────────\n\n"
                "請您耐心等候叫號，輪到您的號碼時醫師會與您看診。"
                "如果您感到非常不舒服，請立即告知現場護理師。"
            )

    return {
        "reply": reply,
        "session_id": req.session_id,
        "completed": completed,
        "user_display": user_display,
        "step": session["step"],
        "queue_number": queue_number,
    }


def retrieve_context_block(query: str, n_results: int = 6) -> tuple[str, list[dict]]:
    """
    執行一次 RAG 檢索，回傳 (整理好的知識庫文字, 來源清單)。
    """
    try:
        chunks = retrieve(query, n_results=n_results)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"向量庫查詢失敗：{str(e)}")

    seen_titles = set()
    context_parts = []
    sources = []
    for chunk in chunks:
        title = chunk["title"]
        if title in seen_titles:
            continue
        seen_titles.add(title)
        context_parts.append(f"[{chunk['source']} — {title}]\n{chunk['text'][:900]}")
        sources.append({
            "title": title,
            "source": chunk["source"],
            "url": chunk.get("url", ""),
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

    try:
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀", n_results=5
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查", n_results=4
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波", n_results=4
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

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": STRUCTURED_NOTE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        structured_note = response.choices[0].message.content.strip()
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
        diag_context, diag_sources = retrieve_context_block(
            f"{base_query} 鑑別診斷 危險徵兆 紅旗症狀", n_results=5
        )
        lab_context, lab_sources = retrieve_context_block(
            f"{base_query} 抽血檢驗 實驗室檢查", n_results=4
        )
        imaging_context, imaging_sources = retrieve_context_block(
            f"{base_query} 影像學 X光 電腦斷層 CT MRI 超音波", n_results=4
        )
        sources = _dedup_sources(diag_sources, lab_sources, imaging_sources)
    else:
        context_block, sources = retrieve_context_block(base_query, n_results=6)

    patient_block = ""
    if patient:
        patient_block = f"""目前正在討論的病人（問診編號 {patient['queue_number']}）：

{patient['summary']}

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
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        reply = response.choices[0].message.content.strip()
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
