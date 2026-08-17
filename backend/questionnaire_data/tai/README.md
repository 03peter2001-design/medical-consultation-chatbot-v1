# 台語問卷產物

此目錄由上層 `translate_to_taigi.py` 產生。腳本會讀取
`questionnaire_data/*.json` 與 `questionnaire_data/ui/patient_messages.json`，使用
`Bohanlu/Taigi-Llama-2-Translator-7B` 的 `HAN` 目標語言產生台語漢字版本；國語來源
不會被覆寫。

產生的 JSON 會保留 `field`、`kind`、policy、semantic code 與其他結構化臨床邏輯，
只轉換顯示文案、選項以及引用選項文字的條件。`_translation_manifest.json` 記錄來源
與輸出 SHA-256、模型 revision、生成參數及授權。

所有輸出均標示為 `machine_translated_unreviewed`。模型翻譯不得視為台語或臨床簽核，
也不得直接取代現行問卷；正式使用前須由合格的台語與臨床人員逐題審查。模型授權為
CC BY-NC-SA 4.0，院所或商業用途須先完成授權審查。

審查完成後，manifest 必須明示 `review_status: clinically_reviewed`，並記錄
`review.reviewer`、`review.reviewed_on` 與 `review.scope`；每個輸出的 hash 也必須與
審查後內容一致。Backend 對未審核、缺少審查身分、來源漂移或輸出被改動的資產一律
拒絕載入。
