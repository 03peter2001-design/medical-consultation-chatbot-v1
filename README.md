# 胸痛問診機器人（Chest Pain AI Doctor）

AI 輔助預問診系統。使用者（病患端）用文字或語音回答一系列問題，系統會即時判斷主訴類型（胸痛／頭痛／腹痛），走對應的問診流程，最後透過 LLM（Groq）產生一份結構化的 AI 初步評估報告；醫師端則可以用問診編號查詢病人資料、閱讀 AI 報告，並針對追加的補充資訊自動生成結構化病歷分析。

## 目前功能

- **病患端**（`index.html`）：文字或語音輸入問診、D-ID 虛擬數位人語音互動、即時進度條、完成後產生 AI 初步評估報告與問診編號
- **醫師端**（`doctor.html`）：輸入問診編號載入病人資料、查看 AI 報告、可另外輸入病人口語補充內容，系統會自動生成六段式結構化病歷分析
- **RAG（檢索增強生成）**：`backend/docs/` 裡有三份醫學文章（急診醫學／感染科／檢驗醫學），會被向量化存進 `chroma_db`，AI 產生報告時會引用裡面的醫學知識佐證
- 目前支援 3 種問診情境：**胸痛、頭痛、腹痛**，系統會依照使用者第一句主訴自動判斷走哪一套問題流程

## 專案結構

```
ai-doctor/
├── index.html              # 病患端網頁
├── doctor.html              # 醫師端網頁
├── backend/
│   ├── main.py               # FastAPI 後端主程式（問診流程、LLM呼叫、API）
│   ├── rag.py                 # RAG 檢索邏輯
│   ├── ingest.py              # 建立向量資料庫用的腳本
│   ├── requirements.txt       # Python 套件需求
│   ├── docs/                  # RAG 知識庫來源文件（.txt）
│   ├── .env                   # 環境變數（需自行建立，不會上傳到 GitHub）
│   └── chroma_db/              # 向量資料庫（需自行執行 ingest.py 產生，不會上傳到 GitHub）
└── pic/                     # 圖片素材
```

> `.env` 和 `chroma_db/` 都被排除在版本控制之外（見 `.gitignore`），所以 clone 下來之後**必須自己重新建立**，步驟見下方。

## 安裝與啟動步驟

### 1. 下載專案

```bash
git clone https://github.com/03peter2001-design/chest-pain-ai-doctor.git
cd chest-pain-ai-doctor
```

### 2. 設定後端環境

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 建立 `.env`

在 `backend/` 資料夾裡新增一個叫 `.env` 的檔案，內容：

```
GROQ_API_KEY=你的Groq API Key
```

去 [Groq Console](https://console.groq.com/keys) 申請一組免費的 API Key。

### 4. 建立向量資料庫（RAG）

`backend/docs/` 裡已經附上三份醫學文章，執行以下指令會自動建立 `chroma_db/`：

```bash
python ingest.py
```

看到終端機顯示建立完成即可（這步驟只需要做一次；之後如果修改了 `docs/` 裡的文件，要重新執行一次這個指令）。

### 5. 啟動後端

```bash
uvicorn main:app --reload
```

後端預設會跑在 `http://127.0.0.1:8000`。看到終端機顯示 `[RAG] 向量庫已載入，RAG 功能啟用` 代表 RAG 有正確載入。

### 6. 開啟前端

回到專案根目錄，直接用瀏覽器打開：

- `index.html` → 病患端（開始問診）
- `doctor.html` → 醫師端（輸入問診編號查詢病人）

> 建議用 VS Code 的 Live Server 或任何簡易本地伺服器開啟這兩個 html，避免瀏覽器對 `file://` 路徑的限制。

### 7.（選用）設定 D-ID 虛擬數位人語音互動

病患端網頁左側有一個「D-ID 設定」欄位，需要輸入：
- **Client Key**：去 [studio.d-id.com](https://studio.d-id.com) 註冊後取得
- **Agent ID**：在 D-ID Studio 建立一個 Agent 後取得

不填這兩個欄位一樣可以用純文字/語音輸入方式問診，只是不會有虛擬數位人開口說話的效果。

## 測試用假病人（醫師端）

醫師端輸入問診編號 **`00000`** 可以直接載入一筆預先寫好的測試胸痛病人資料，方便開發/展示時不用每次都重新跑一次完整問診。這筆資料的 AI 初步評估是預先寫死的文字（並非即時呼叫模型產生），報告內文有清楚標註「測試用假病人資料」，不會被誤認為真實案例。

## 常見問題

**Q: 啟動後端時出現 `[RAG] 未找到 chroma_db，請先執行 python ingest.py`？**
A: 代表你還沒建立向量資料庫，回到步驟 4 執行 `python ingest.py`。

**Q: 前端顯示無法連線到後端？**
A: 確認 `backend` 有用 `uvicorn main:app --reload` 跑起來，且網址是 `http://127.0.0.1:8000`（在 `index.html` / `doctor.html` 裡的 `BACKEND` 變數可以確認/修改）。

**Q: `.env` 或 `chroma_db` 不見了？**
A: 這是正常的，這兩個東西本來就不會被上傳到 GitHub（見 `.gitignore`），照步驟 3、4 自己重新建立即可。

## 開發規劃

- [ ] 目前問診題目是寫死在 `backend/main.py` 裡（`CHEST_QUESTIONS` / `HEADACHE_QUESTIONS` / `ABDOMEN_QUESTIONS`），下一版計畫改成獨立的 JSON 檔案管理，方便之後修改題目不用動到程式碼本身
