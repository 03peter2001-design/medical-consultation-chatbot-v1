"""
questionnaire_loader.py
────────────────────────
從 questionnaires/ 資料夾讀取問卷 JSON 檔案，組成 main.py 可以直接使用的登記表（registry）。

── 之後要新增問卷（還有 49 份）的做法 ──
1. 在 questionnaires/ 資料夾新增一個 <type>.json 檔案（檔名用英文，例如 headache.json、abdomen.json）
2. 照著 chest.json 的格式填寫（可以直接複製 chest.json 當範本）
3. 重啟後端，程式會自動掃描載入，不需要改 main.py 或這個檔案

── 單一問卷 JSON 的格式說明 ──
{
  "id": "chest",              # 問卷代號，建議跟檔名一致（不含 .json）
  "label": "胸痛",             # 顯示用的中文名稱，會用在「了解，您說的是＿＿的問題」這句話裡
  "suggested_orders": ["12導程心電圖（ECG）", "心肌酵素（Troponin）抽血", "胸部X光"],
                               # 選填。問完這份問卷後，AI 預設建議醫師考慮開立的檢查／檢驗草稿，
                               # 不會自動送出，一定要醫師在醫師端按「確認醫囑」才會生效。
                               # 沒寫這個欄位就是空清單。
  "questions": [
    {
      "key": "onset",         # 這一題的答案會存進 data["onset"]
      "type": "onset",        # 選填。標記為 "onset" 的題目，答案會用 parse_onset() 額外拆成
                               # data["onset_num"]（數字）跟 data["onset_unit"]（分鐘前/小時前/天前…）
      "text": "胸痛從什麼時候開始的？"
    },
    {
      "key": "chronic_detail",
      "text": "您提到了需要進一步說明的疾病，請簡單描述一下病名。",
      "condition": {           # 選填。沒有 condition 代表這一題一定會問。
        "field": "chronic",    # 依據「哪一題」的答案來判斷要不要問這一題
        "contains_any": ["自體免疫疾病", "癌症", "其他"]
                                # 只要 field 那一題的答案包含以上任一關鍵字，才會問這一題；
                                # 否則自動跳過，直接問下一題
      }
    },
    {
      "key": "side",
      "text": "是左邊還是右邊？",
      "options": ["左邊", "右邊"]
                                # 選填。答案是固定選項的題目才需要加這個欄位（性別、是否、
                                # 左右...等）。加了之後，系統會自動用通用的語音校正機制
                                # （normalize_choice_answer，見 main.py）處理誤聽，答案一定
                                # 會被校正成 options 裡的其中一個字串，無法判斷時會重問同一題，
                                # 不需要再為每一題手動維護同音字清單。
                                # 沒有加這個欄位的題目，答案就是照使用者說的原文存起來（適合
                                # 開放式描述性的題目，例如「你會如何描述這種疼痛？」）。
    }
  ]
}

題目會照 questions 陣列裡的順序，一題一題往下問，问完全部（略過不符合 condition 的題目）
就會自動進到「生成 AI 初步評估報告」的流程，跟舊版胸痛/頭痛/腹痛問完之後的行為完全一樣。
"""

import json
import os
from typing import Any

_QUESTIONNAIRES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questionnaires")


def load_questionnaires(directory: str = _QUESTIONNAIRES_DIR) -> dict[str, dict[str, Any]]:
    """
    掃描 directory 底下所有 .json 檔（檔名以 "_" 開頭的會略過，保留給未來共用設定用），
    回傳 {問卷id: 問卷內容dict} 的登記表。

    任何一個檔案格式錯誤，只會印出警告並略過該檔，不會讓整個後端啟動失敗，
    這樣之後陸續新增 49 份問卷時，就算某一份格式寫錯，也不會影響其他已經上線的問卷。
    """
    registry: dict[str, dict[str, Any]] = {}

    if not os.path.isdir(directory):
        print(f"[Questionnaire] 找不到問卷資料夾：{directory}")
        return registry

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json") or filename.startswith("_"):
            continue

        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                spec = json.load(f)
        except Exception as e:
            print(f"[Questionnaire] 讀取失敗，略過 {filename}：{e}")
            continue

        qid = spec.get("id") or filename[:-5]

        if "questions" not in spec or not isinstance(spec["questions"], list) or not spec["questions"]:
            print(f"[Questionnaire] {filename} 缺少合法的 questions 陣列，略過")
            continue

        bad_question = next(
            (q for q in spec["questions"] if not isinstance(q, dict) or "key" not in q or "text" not in q),
            None,
        )
        if bad_question is not None:
            print(f"[Questionnaire] {filename} 有題目缺少 key 或 text 欄位，略過整份問卷")
            continue

        registry[qid] = spec
        print(f"[Questionnaire] 已載入問卷「{spec.get('label', qid)}」({qid})，共 {len(spec['questions'])} 題")

    return registry
