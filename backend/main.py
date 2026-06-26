from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from groq import Groq
from dotenv import load_dotenv
import os
import re
import time

load_dotenv()

app = FastAPI(title="AI 預問診系統", version="1.1.0")

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


def parse_gender(text: str) -> str:
    if any(w in text for w in ["男", "先生", "男性", "男生"]):
        return "男"
    if any(w in text for w in ["女", "小姐", "女性", "女生"]):
        return "女"
    return text


def parse_age(text: str) -> str:
    numbers = re.findall(r"\d+", text)
    age = int(numbers[0]) if numbers else None
    if age and (0 < age < 130):
        return str(age)
    return text


def build_report_prompt(data: dict) -> str:
    return f"""
你是一位專業醫療預問診助理。

請根據以下資訊：

就診原因：{data.get("reason", "未提供")}
性別：{data.get("gender", "未提供")}
年齡：{data.get("age", "未提供")}
症狀：{data.get("symptom", "未提供")}
病史：{data.get("history", "無")}

請用繁體中文輸出以下格式（每區塊簡短）：

【基本資料】
性別：XXX　年齡：XXX

【症狀統整】
簡短整理目前症狀與病史（2～3句）

【初步判斷】
可能方向（1～2句，不做正式診斷）

【建議】
是否建議休息、觀察或就醫（1句）

限制：
1. 總長不超過200字
2. 語氣自然親切，不過度正式
3. 絕對不做正式診斷
"""


@app.get("/health")
def health():
    return {"status": "ok", "sessions": len(sessions)}


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
            prompt="用戶描述身體症狀，說繁體中文。常見詞：喉嚨痛、發燒、頭痛、咳嗽、全身痠痛、流鼻水、肚子痛。",
        )
        text = str(transcription).strip()
        return {"text": text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"語音辨識失敗：{str(e)}")


@app.post("/chat")
async def chat(req: ChatRequest):
    _cleanup_sessions()

    if req.session_id not in sessions:
        sessions[req.session_id] = {"step": 0, "data": {}, "ts": time.time()}
        return {
            "reply": "您好，我是AI預問診助理，請描述本次不舒服的原因。",
            "session_id": req.session_id,
            "completed": False,
        }

    session = sessions[req.session_id]
    session["ts"] = time.time()
    step = session["step"]
    data = session["data"]
    user_input = req.message

    if step == -1:
        return {
            "reply": "本次預問診已完成，請重新整理頁面開始新的問診。",
            "session_id": req.session_id,
            "completed": True,
        }

    if not user_input:
        return {"reply": "請輸入內容後再送出。", "session_id": req.session_id, "completed": False}

    reply = ""
    completed = False

    if step == 0:
        data["reason"] = user_input
        session["step"] = 1
        reply = "請問您的性別？"

    elif step == 1:
        data["gender"] = parse_gender(user_input)
        session["step"] = 2
        reply = "請問您的年齡？"

    elif step == 2:
        data["age"] = parse_age(user_input)
        session["step"] = 3
        reply = "請簡單描述主要症狀（例如頭痛、發燒、咳嗽等）。"

    elif step == 3:
        data["symptom"] = user_input
        session["step"] = 4
        reply = "請問有慢性病或相關病史嗎？（若無請回答「無」）"

    elif step == 4:
        data["history"] = user_input if user_input else "無"

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "你是醫療預問診助理。請用繁體中文、簡短自然方式回答。絕對不可做正式診斷。",
                    },
                    {"role": "user", "content": build_report_prompt(data)},
                ],
                temperature=0.3,
                max_tokens=300,
            )
            reply = response.choices[0].message.content.strip()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI 生成失敗：{str(e)}")

        session["step"] = -1
        completed = True

    return {"reply": reply, "session_id": req.session_id, "completed": completed}