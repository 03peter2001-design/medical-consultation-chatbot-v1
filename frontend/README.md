# Vue 前端

`frontend/` 是 Vue 3 + Vite 應用，包含病患問診、醫師工作區、規則中心與
SNOMED CT 查詢。根目錄的 `index.html`、`doctor.html` 是重構前的相容版本，
不再是主要開發入口。

## 服務版本

### v0.9.0 (2026-08-20)

- 開發版 Vite 新增同源 `/ai-consult/launch.html` SMART EHR Launch 入口，依 launcher
  提供的 `iss`／`launch` 執行 OAuth，callback 固定回到 `/ai-consult/?smart=1`，再由
  既有病患頁讀取 launch-context `Patient`、`Encounter` 與
  `Patient/{id}/$everything` Bundle。
- SMART client 固定為既有 sandbox 使用的 `fhirclient` 2.6.3，採本地 npm bundle，
  不從 CDN 載入；scope 維持唯讀 `launch patient/*.read`，access token 只供瀏覽器
  呼叫 FHIR Server，不會放入問診 prefill、送往 Backend、RAG 或外部模型。
- Launch issuer 僅接受無帳密的 HTTP(S) URL；缺少或無效的 `iss`／`launch` 會明確
  fail closed。Hash router 明確綁定 `/ai-consult/` base，callback 清除 authorization
  code 時保留 router history state；`frontend-v2/` 與 SMART sandbox 部署線未修改。
- Node 22 的 16 組 Node tests、Vite multi-page production build 與 OpenAPI type drift
  check 通過；Browser plugin／Playwright 不可用，故以 headless Chrome 驗證 1280×800
  與 390×844 的 launch fail-closed 畫面、既有病患首頁、無水平溢出或應用程式 console
  error。實際院方 OAuth／FHIR round trip 仍需可連線的 Launcher、client registration 與
  合成測試病人。

### v0.8.4 (2026-08-20)

- 將病患端疼痛位置圖與同題原問卷選項合併為單一題卡；問診畫面不再同時顯示圖內
  精細位置 checkbox 清單與下方原問卷選項。
- 位置題只保留下方原問卷選項與一個「確認答案」按鈕；點圖仍會自動勾選對應選項，
  點選項仍會反向標示圖上範圍，精確圖形位置會隨同原問卷答案送出。
- Node 22 的 15 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，故以 headless Chrome 驅動真實 Vue 元件，驗證
  1440×960 與 390×844 均只有一組選項與一個確認按鈕，雙向同步正常，無水平溢出或
  runtime error；`frontend-v2/` 未修改。

### v0.8.3 (2026-08-20)

- 醫師病例卡頂部的「基本資料」與「主訴分類」改為帶色彩識別與左側強調線的資訊卡，
  同時提高內容字級、字重與對比，讓醫師進入病例後能更快辨識關鍵身分及主訴資訊。
- 手機版將兩張資訊卡改為單欄排列並保留可讀字級；摘要與臨床紅旗警訊的既有層級及
  資料內容均未變更，`frontend-v2/` 未修改。
- Node 22 的 15 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，故以 headless Chrome 驅動真實 Vue 元件，驗證
  1440×960 與 390×844 的兩張資訊卡均可見、內容字級至少 16px，且無水平溢出。

### v0.8.2 (2026-08-20)

- 將人體疼痛圖與同題下方原有問卷選項接成雙向同步：點精細圖上區域後，
  胸痛、頭痛、腹痛的既有 canonical options 會依明確映射自動勾選；從問卷選項操作
  時，圖上會反向標示對應範圍。
- 粗粒度選項不會作為精細 `pain_location_ids` 送出；例如僅選「前額」只標示可能範圍，
  不臆測成左側、右側或雙側精確疼痛。點圖指定「右前額」時則可確定性對應為「單側＋
  前額」；此 UI 映射不新增診斷或安全規則，`frontend-v2/` 未修改。
- Node 22 的 15 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，故以 headless Chrome 驅動真實 Vue 元件，驗證
  1440×960 與 390×844 的圖→原問卷選項、原問卷選項→圖雙向互動，無水平
  溢出或 runtime error。

### v0.8.1 (2026-08-20)

- 修正問診單選與複選選項的 click handler：不再阻止瀏覽器原生 checked 狀態更新，
  因此選項背景變色時，radio／checkbox 也會同步顯示勾選。
- 保留既有「再點一次可取消」、單選互斥、複選與排他選項規則；`frontend-v2/`
  未修改。
- Node 22 的 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，故以 headless Chrome 驅動真實 Vue 元件，驗證
  1440×960 與 390×844 的選取、取消、恢復勾選與視覺狀態，無水平溢出或
  runtime error。

### v0.8.0 (2026-08-20)

- 病患端人體疼痛圖新增依正面／背面切換的部位 checkbox 清單；點擊圖上區域會
  自動勾選對應選項，勾選或取消選項也會同步更新圖上標示。
- 圖與清單共用同一組結構化 region IDs，保留複選、清除、鍵盤操作、疼痛位置文字及
  Backend `pain_location_ids` 送出格式；`frontend-v2/` 未修改。
- Node 22 的 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，故以 headless Chrome 驅動真實 Vue 元件，驗證
  1440×960 與 390×844 的圖→checkbox、checkbox→圖雙向互動，無水平溢出或
  runtime error。

### v0.7.3 (2026-08-20)

- 修正七段英文 EMR 的 heading parser：同時支援 Chief Complaint／CC、Present
  Illness／PI、Past History／PH、Meds／Current Medications／Drug History、Allergy／
  Allergy History／Drug Allergy History，以及 Personal History、Family History。
- Personal／Family History 現在各自顯示為醫師摘要資料列；解析 Allergy History 後不再
  把後續個人史、家族史文字附加到過敏內容。舊五欄病例格式與缺漏時的結構化資料回退
  維持相容；`frontend-v2/` 未修改。
- Node 22 的 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過。
  本工作階段沒有 Browser plugin，專案也未安裝 Playwright，因此未執行 rendered browser
  QA；七段合成病例由 parser 與元件契約回歸測試覆蓋。

### v0.7.2 (2026-08-20)

- 修正醫師摘要的欄位對應：依既有 EMR heading 將 CC、PI、PH、Meds、Allergy
  分別呈現為 CC、PI、PHx、DHx、AHx，不再把完整結構化報告塞入 PI。
- 舊病例若沒有可解析 heading，僅以既有主訴、發作時間、病史、用藥與過敏結構化欄位
  個別回退；缺少內容時明示未提供，不進行臨床推測。本次未更動後端資料契約，亦未修改
  `frontend-v2/`。
- Node 22 的 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，因此另以合成病例透過 headless Chrome CDP 驗證
  1440×960 與 390×844 的五列資料、來源標示及響應式排列，無水平溢出或 console
  warning／error。

### v0.7.1 (2026-08-20)

- 優化醫師病例的 RAG 病歷／文獻摘要 disclosure：收合時保留 RAG 標識、AI provenance、
  病況首行預覽與來源數量，展開後才顯示完整摘要和來源 tags；SVG chevron、hover、focus
  與旋轉狀態明確提示可互動性。
- 手機將來源數與展開控制移至標題下方，摘要預覽允許自然換行；桌機維持緊湊單列，
  兩種版面都沿用既有 teal、左側強調線與臨床文件密度。本次未修改 `frontend-v2/`。
- Node 22 的 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過；
  Browser plugin／Playwright 不可用，因此另以合成病例透過 headless Chrome CDP 驗證
  1440×960 收合／展開與 390×844 收合狀態，無水平溢出或 console warning／error。

### v0.7.0 (2026-08-20)

- 醫師病例工作區依新介面草圖重排為單一臨床文件：基本資料與出生日期、主訴、三欄
  關鍵症狀／重要病史／疼痛位置、01–05 AI 臨床決策、RAG 病歷／文獻摘要，以及
  CC／PI／PHx 醫師摘要資料列，並保留病例資料庫與既有問答功能。
- AI 決策、RAG 摘要與資料彙整草稿均明示待醫師確認；紅旗警訊維持在上方，來源、
  固定規則、疾病票數及問診軌跡移入可展開的稽核區，未把 Gemini 內容標成醫師已確認。
- 桌面使用開放式三欄快照與雙欄決策模組，手機改為單欄並將完整標題與可橫向捲動的
  工具列分列顯示；本次只修改 `frontend/` 開發版，未同步 `frontend-v2/` 部署版。
- 使用 Node 22 執行 14 組 Node tests、Vite production build 與 OpenAPI type drift
  check，全部通過。由於 Browser plugin／Playwright 不可用，另以合成病例透過
  headless Chrome CDP 驗證 1440×960 與 390×844：區塊順序、五張決策卡、稽核區
  展開及響應式版面正確，無水平溢出或 console warning／error。

### v0.6.1 (2026-08-18)

- Vite 開發伺服器加入 Vue DevTools，供本機檢查元件樹、狀態與互動；plugin 自身限制
  `apply: serve`，不注入 production build。
- 新增項目只屬開發依賴與 Vite 設定，不改變病患／醫師 runtime 契約，也未修改
  `frontend-v2/` 部署版。
- 使用主機既有 Node 24 執行 14 組 Node tests、Vite production build 與 OpenAPI
  type drift check，全部通過。

### v0.6.0 (2026-08-18)

- 醫師病例工作區不再把六段式臨床總結塞在單一純文字區域；EMR、前三鑑別、防漏診、
  理學檢查、檢驗與影像會依固定 heading 解析成獨立、醒目的問題卡片。
- 每張卡片顯示可快速掃讀的臨床問題、段落名稱與原始模型內容；防漏診使用紅色識別，
  其他段落依用途使用不同 accent，桌面為雙欄、窄螢幕自動改為單欄。
- 保留既有 EMR 上方摘要、RAG sources、模型 provenance、舊無 heading 報告 fallback，
  並同時相容 `理學檢查`／`理學檢查建議` 與兩種檢驗標題。本次未修改獨立控制的
  `frontend-v2/` 部署版。
- 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過（Node 22）。
  另以合成病例在 headless Chrome 驗證 1440×960 雙欄與 390×844 單欄版面：五張臨床
  決策卡均位於 EMR 下方，沒有水平溢出、Vite overlay 或 console warning／error。

### v0.5.0 (2026-08-17)

- 本機直連 HAPI 的開始問診畫面新增 identifier 類型選擇，除了台灣身分證
  字號，也可以 Synthea Default ID 查詢匯入的合成病人。
- Synthea 模式以 `https://github.com/synthetichealth/synthea|<UUID>` 精確搜尋
  `Patient.identifier`；不把 Default ID 當成 HAPI `Patient.id`，而是以搜尋回傳的
  resource ID 讀取 `$everything`。
- 兩種 identifier 皆有獨立格式驗證與查無／重複資料的 fail-closed 訊息；Synthea
  資料仍是美國合成測試資料，不因此視為 TW Core 相容或真實病人資料。

### v0.4.1 (2026-08-13)

- API HTTP 錯誤與真正的網路連線失敗分開顯示；台語問卷因未審核而被 Backend 以 503
  拒絕時，畫面直接呈現審核原因，不再誤導使用者檢查 FastAPI host／port。

### v0.4.0 (2026-08-13)

- 開始問診前的語言選擇同時控制問卷與醫師語音，使用穩定 API value
  `mandarin`／`minnan`；選台語時請 Backend 載入經審查的獨立台語問卷資產。
- 問診開始後鎖定語言，避免目前題目與後續驗證跨語系混用；若開始台語問診時資產尚未
  產生、審查或已過期，畫面顯示 Backend 的明確失敗，不會假裝切換成功。
- 選項、快捷時間及單位顯示台語 label，但表單與台語語音辨識會映射回原本 canonical
  value 再送出，確保病歷、條件題及後端驗證格式不因顯示語言改變。
- 14 組 Node tests、Vite production build 與 OpenAPI type drift check 通過（Node 22）。

### v0.3.0 (2026-08-11)

- 本地 Avatar 回傳靜態醫師 MP4 後，病患問診舞台持續顯示醫師與當次朗讀字幕，並
  保留原有聊天文字與問卷互動；影片直接承載 CosyVoice3 音訊，不另啟音訊播放器。
- 有聲自動播放若遭瀏覽器政策阻擋，影片原生 controls 與舞台上的「播放醫師語音」
  按鈕提供明確的使用者手勢播放入口；成功播放後同步既有說話狀態。
- 變更只作用於病患 Avatar 舞台，醫師工作區與獨立部署的 `frontend-v2/` 不受此版號
  管理。

### v0.2.6 (2026-08-10)

- 醫師工作區的六段式病歷說明把「檢驗建議」改為「檢驗（抽血／驗尿）」，與後端
  新報告標題一致；病歷仍標示為 Gemini 生成、未經醫師確認的臨床決策草稿。
- 舊病例的 AI terminology badge 改標示為「AI 編碼結果，待醫師確認」，不再使用
  「AI 建議編碼」字樣；保留來源與人工確認邊界。
- Structured note regression test 驗證新標題並防止報告說明恢復「建議」字樣；未修改
  獨立控制的 `frontend-v2/` 正式部署線。

### v0.2.5 (2026-08-10)

- 更新病患／醫師流程文件：固定問卷完成後顯示的是 Gemini 依完整題目與答案生成的
  EMR 草稿，不再描述為 deterministic EMR；前端 runtime 與 bundle 未變更。
- 文件同步說明新 `questionnaire` 病例不建立疾病票數；OpenAPI type drift check 通過。

### v0.2.4 (2026-08-10)

- 開始頁仍保留完整 Avatar 舞台與 fallback；進入問診後，只有 connected、connecting、
  rendering 或 talking 時顯示舞台，未啟用／啟用失敗時自動收合，讓文字問診使用主要空間。
- 收合摘要列直接顯示 Avatar 失敗原因；展開設定後仍提供啟用／重試控制。成功啟用後
  舞台會自動出現，既有設定顯示／隱藏行為不變。
- Avatar focused regression、完整 Node tests、production build、OpenAPI type drift
  check 通過；headless Chrome/CDP 驗證模擬 GPU 不可用的桌機／390×844 收合狀態、
  重試入口及成功啟用對照，無 Vite overlay、console warning/error 或 runtime exception。

### v0.2.3 (2026-08-10)

- 開始問診頁仍直接顯示完整 Avatar 設定；進入問診後預設收合成一列，保留 provider、
  語言摘要及「顯示」按鈕，病人可 inline 展開或再次隱藏，不使用 drawer／modal。
- 展開按鈕同步 `aria-expanded` 與 `aria-controls`，支援鍵盤 focus；桌機與手機收合時
  都不占用問卷主要內容空間，題目、進度與輸入控制維持可用。
- Avatar focused regression、完整 Node tests、production build、OpenAPI type drift
  check 通過；headless Chrome/CDP 驗證開始頁可見、問診預設收合、展開、再收合及
  390×844 響應式狀態，無 Vite overlay、console warning/error 或 runtime exception。

### v0.2.2 (2026-08-10)

- 本地 Avatar 的 CosyVoice3／MuseTalk 影片改為獨立背景生成狀態；後端回傳下一題後，
  題目與輸入控制立即可用，不再把影片生成呈現為整個 Avatar 重新連線或要求病人等待。
- 快速連續作答時合併尚未開始的 Avatar 工作，只保留最新題目；已在執行的工作完成後
  若已過時便不播放，避免舊題影片逐題累積、晚於目前問診進度才出現。
- 舞台與 Header 明示「背景生成中，可直接作答」；連線 warm-up、問卷 Safety、答案
  保存及完成後 EMR 行為不變。
- Unit regression test 驗證連線在生成期間保持可用且第二個過時工作不會執行；以
  headless Chrome/CDP 攔截慢速 Avatar，在首個影片請求保持 pending 時連續送出兩題，
  下一題分別於 31ms／8ms 可操作，且只送出第一題與最新第三題影片工作。此數值是本機
  模擬回應的 UI 非阻塞證據，不代表正式 GPU 推論時間。完整 Node tests、production
  build 與 OpenAPI type drift check 通過。

### v0.2.1 (2026-08-10)

- 修復 `v0.2.0` 將 Avatar 舞台、設定與開始流程全部垂直堆疊，導致常見筆電與手機
  首屏看不到身分欄位和開始按鈕的響應式版面 regression。
- 桌機改為 Avatar／常駐設定與開始流程雙欄配置；窄螢幕依序顯示 Avatar、開始流程、
  常駐設定，保留 provider 與語言直接可操作且不恢復 drawer。
- 以 1366×768、390×844 headless Chrome/CDP 驗證主要按鈕首屏可見、D-ID provider
  切換、無 Vite overlay、console warning/error 與 runtime exception。

### v0.2.0 (2026-08-10)

- Avatar 設定不再藏在左側 drawer；provider、醫生說話語言、模型名稱、目前狀態及
  啟用／中斷控制直接常駐於開始問診頁與問診中的主舞台下方。
- 切換 D-ID 後，Client Key 與 Agent ID 在同一控制區直接顯示，並保留資料傳輸與
  Browser／Embed Key 警告；本地 provider 則顯示院內模型與首次載入說明。
- 移除 Header Avatar panel 按鈕、modal backdrop 與 drawer state；桌面使用緊湊橫向
  控制列，手機改為可直接捲動的單欄表單，Avatar 失敗時文字問診 fallback 不變。
- Avatar regression tests、完整 Node tests、production build、OpenAPI type drift，
  以及 headless Chrome 桌面／手機畫面與 provider 切換互動驗證通過。

### v0.1.0 (2026-08-10)

此版本配合簡化問診方向重新以 0 編碼；下方 `v1.x` 條目是先前能力線的歷史紀錄，
不是目前發布線的連續 SemVer 前序版本。

- 本機 Avatar 在病患頁載入時自動 warm-up／連線，不再要求病人先進設定抽屜手動啟用；
  開始問診 overlay 與問診頁首屏都以放大的醫師舞台作為主視覺。
- 未連線、載入中、已連線與失敗狀態都保留醫師圖、可讀狀態及字幕區；失敗時明示
  文字問診仍可使用，並提供可用鍵盤操作的重試按鈕，不會因 Avatar 中斷問診。
- 病患頁移除 AMIE trace 狀態與面板；前端仍保留其他醫師端治理／歷史相容元件，且
  沒有修改獨立控制的 `frontend-v2/` 正式部署線。
- 14 個 Node test files、production build、OpenAPI type drift，以及 headless Chrome
  1440×960／390×844 首屏、fallback、重試互動、DOM 與 console 驗證通過。

### v1.7.0 (2026-08-10)

- 將既有 Breeze ASR 語音輸入延伸至選擇、複選、持續時間與日期題；結構化題目
  顯示獨立麥克風、收音波形與辨識狀態，Avatar 播放完問題後也可自動開始錄音。
- 語音只以確定性規則套用 exact choice、核准時間單位，以及有效的西元／民國日期；
  無法唯一對應時保留為允許的「其他／補充說明」，或要求病人手動作答，不做語意猜測。
- 結構化語音答案一律先填入現有控制項並由病人確認後送出；只有自由文字題維持既有
  3 秒自動送出，因此 ASR 誤辨不會直接提交選項、日期或時間答案。
- 14 個 Node test files、production build、OpenAPI type drift，以及系統 Chrome 的
  1440×960／390×844 結構化麥克風互動與錄音狀態驗證通過。

### v1.6.0 (2026-08-10)

- 本地 Avatar 檢查服務、warm-up 載入 Breeze／CosyVoice／MuseTalk，以及產生語音
  影片期間，設定抽屜與中央醫師舞台都顯示目前階段、轉動指示與等待說明，避免長時間
  GPU 載入看似沒有反應；狀態區使用 `aria-live`／`aria-busy` 通知輔助科技。
- 錄音期間使用既有 Web Audio analyser 的 RMS 音量驅動七段即時波形；高於語音
  閾值後明確顯示「已收到聲音」。手動錄音與 Avatar 自動錄音都有視覺回饋，但只有
  Avatar 自動錄音維持說話後靜音 5 秒自動送交辨識的行為。
- 波形在窄螢幕縮成圖像提示，保留文字輸入、停止錄音與送出按鈕空間；降低動態偏好
  會停用 spinner 動畫與 waveform transition。

### v1.5.0 (2026-08-10)

- 本機 Avatar 設定新增「醫生說話語言」，可自由切換國語與閩南語；選擇值隨每次
  合成請求傳入，中央字幕標籤同步顯示目前語言。
- 啟用本機 Avatar 時先呼叫受保護的 warm-up API，待 Breeze ASR、CosyVoice3 與
  MuseTalk 全部 loaded 才進入已啟用狀態，後續問答不再重複載入模型。
- Breeze ASR 回傳空文字或失敗時，保留失敗狀態並由已連線醫生說「對不起，我沒有
  聽清楚，請再講一次」，播放結束後重新開始語音輸入。
- Node regression tests、Vite build、OpenAPI drift 與 Chrome 互動驗證涵蓋語言選擇、
  warm-up、重試提示及桌面／手機版顯示。

### v1.4.0 (2026-08-10)

- 修正 Vite 開發模式找不到 `/avatar/doctor.png` 的問題，改由 frontend build
  帶入既有醫師圖片；本機 Avatar 啟用後在問診畫面上方顯示置中的醫師舞台，
  並在旁邊同步顯示目前朗讀字幕。
- Avatar 播放完畢後，文字題預設開啟語音輸入；實際偵測到使用者開始說話後，
  連續靜音 5 秒會停止錄音、呼叫 Breeze ASR，並準備自動送出。
- ASR 結果先回填下方輸入框並保留 3 秒編輯時間；使用者開始輸入即取消自動
  送出，也可手動停止錄音後自行確認與送出。未啟用 Avatar 時維持既有手動語音流程。
- Node tests、OpenAPI type drift、Vite production build，以及實際 Chrome 桌面／手機
  viewport 的 Avatar 圖片、字幕、輸入列與預設錄音流程驗證通過。

### v1.3.0 (2026-08-10)

- 開發版 frontend 的預設 API port 改為 `18000`，固定連到 integration Compose
  提供的 host-loopback Nginx gateway，避免與仍在 `8000` 的本機 Uvicorn 衝突。
- Frontend 繼續由 Vite hot reload；backend、病例資料庫、Breeze ASR 與 Avatar
  統一由 Docker Compose 提供。跨來源 credentials 既有的 fail-closed 行為不變。
- 更新 backend URL regression tests，並以 Node tests、production build 與 API type
  drift check 驗證。

### v1.2.0 (2026-08-09)

- Safety structured-rule editor 分別保存 `all_findings` 與 `any_findings`，切換 operator
  或無修改發布 round-trip 不再遺失另一組條件。
- 顯示兩組 finding 數量以及目前搜尋／分類 filter 隱藏的已選項目，可明示一次清除，
  避免看不到仍將發布的條件。
- Safety draft assistant 使用 AbortController 與 request sequence；切換群組、取消編輯
  或 component scope dispose 後，過期 response 不會回寫新草稿。
- 同步更新 API error contract types；13 項 Node tests、OpenAPI type drift 與 Vite
  production build 通過。Vue mount/browser interaction test 仍列於根 README 待辦。

### v1.1.0 (2026-08-09)

- Production 與預設開發設定忽略 `backend`、`backendPort`、`fhir`、`directFhir`
  query override；開發 override 必須同時啟用 flag 並通過 exact-origin allowlist。
- Backend request 只在同源時攜帶 credentials；允許的跨來源開發 endpoint 明確使用
  `omit`，避免 session cookie 或身分識別資料被送往任意主機。
- FHIR 本次症狀分類改用獨立、窄版詞表與英文 token boundary，不再讓 `ENT` 等短詞
  誤判 Dementia／developmental／ventricular 等既往病史。
- 醫師病例畫面可為候選或歷史問卷路由顯示穩定 route／欄位標籤；生成問卷 catalog
  可由 backend exporter 以 `--check` 驗證同步。
- 13 項前端測試、OpenAPI 型別 drift 檢查與 Vite production build 均通過（Node 22）。

### v1.0.0（目前文件基線，2026-08-07）

此版號由 `devlog/` 的既有紀錄回溯建立，沒有對應的 Git tag；它描述
`frontend/` 開發版服務截至該日的功能集合，不代表已正式發布、部署或取得臨床
核准。此部署線與 `frontend-v2/` 的 doctor／patient 應用各自獨立演進。API
`/v1`、SQLite schema、RAG collection、疾病表與 Safety 規則另有自己的版本或
revision，不隨此前端版號連動。

此基線包含下列累積更新：

- **2026-07-27 — Vue 應用與多主訴問診基礎**
  - 建立 Vue 3、Vite 與 hash router 架構，提供病患端 `/#/` 與醫師端
    `/#/doctor`。
  - 將病患問診拆成聊天、輸入提示、人體疼痛圖與來源標籤等元件，支援文字、
    語音、單選、複選、自由補充、日期、持續時間及正／背面疼痛位置。
  - 接入胸痛、頭痛與腹痛動態問卷及 FHIR 預填；已由 FHIR 取得的資料可略過，
    身分證字號只用於受控測試環境中的 FHIR 查詢。
  - 建立醫師端病例與 AI 報告檢視，並保留 D-ID Avatar 與純文字問診模式。
- **2026-07-28 — 病患流程與醫師工作台重構**
  - 元件化開始問診、Avatar 設定、結構化問卷、疼痛位置及 AMIE 軌跡面板，
    並擴充前後視圖的身體疼痛區域。
  - 新增醫師病例搜尋、分頁、選取及二次確認刪除，並強化病歷時間軸、臨床
    evidence、FHIR coding、術語與背景摘要狀態的呈現。
  - 更新後端、FHIR、臨床病歷及術語服務封裝與前端測試。
- **2026-07-29 — 規則治理、SNOMED CT 與 SMART 整合**
  - 新增醫師端規則中心，可分類、搜尋及編輯既有 Safety 規則；語意特徵以
    catalog 勾選，發布前仍需完整性檢查、理由與指定確認文字。
  - 新增 SNOMED CT 查詢頁、分頁與錯誤處理，並在疾病方向顯示已驗證的 coding。
  - SMART OAuth 完成後可返回病患問診，讀取 launch-context Patient 與
    `$everything` 預填資料；FHIR access token 不送往 `/chat`、RAG 或外部模型。
  - 改善多主訴已知資訊預填與依病人情境隱藏不適用的問卷選項。
- **2026-08-04 — `/v1` API 與完整規則治理介面**
  - 前端 API client 切換至 `/v1`，加入 OpenAPI TypeScript 型別產生與同步檢查。
  - 將規則中心擴充為疾病票數、ClinicalFact 與 Safety 三個治理介面，支援
    payload 驗證、版本衝突提示、審查資料及發布確認流程。
  - 醫師病例卡新增獨立 EMR 摘要區塊，避免在結構化報告中重複呈現相同內容。
- **2026-08-05 — 候選漏斗與跨日期病例識別**
  - 將大型規則治理畫面拆成選擇器、編輯器、發布面板與 composable，並補上
    payload 正規化、變更偵測、驗證及 filter reset 測試。
  - Clinical Evidence 與 debug trace 可呈現確定性候選漏斗及選題依據；病患端
    debug payload 不暴露疾病名稱、票數或完整排名。
  - 病例卡、載入、刪除及 active state 改用「看診日期＋掛號編號」的 composite
    ID，並把跨日期同號衝突轉為可操作提示。
- **2026-08-07 — 可回上一題、摘要格式與本機語音／Avatar**
  - 結構化問卷支援取消選項、以「其他」文字取代舊選項及返回上一題重新作答；
    body pain map 的左右標示亦提高辨識度。
  - 病例卡將舊摘要相容轉換為固定兩行格式：第一行為主要病況，第二行為兩句
    其他 EMR 病史。
  - 預設接入本機 Breeze-ASR-26 語音辨識，以及 CosyVoice3 + MuseTalk Avatar；
    亦可切換鎖定版本、由本地 bundle 延遲載入的 D-ID provider。
  - loopback-only 開發驗證 bypass 僅接受直接本機連線，正式設定預設關閉。

## 主要目錄

| 路徑 | 用途 |
| --- | --- |
| `src/components/` | 共用 UI 元件 |
| `src/composables/` | 本地／D-ID Avatar provider 狀態與操作 |
| `src/services/` | 後端 API、FHIR 與連線設定 |
| `src/views/` | 病患端、醫師端與術語頁面 |
| `src/generated/` | 由 OpenAPI 產生的型別，不手動編輯 |
| `tests/` | Node 單元測試 |

## 安裝與啟動

需求為 Node.js 18+：

```bash
npm install
npm run dev
```

Vite 會顯示實際網址，預設入口為：

- `http://localhost:5173/ai-consult/#/`：病患端
- `http://localhost:5173/ai-consult/#/doctor`：醫師端
- `http://localhost:5173/ai-consult/#/doctor/terminology/snomed`：SNOMED CT 查詢

其他指令：

```bash
npm test
npm run build
npm run preview
npm run api:types
npm run api:check
```

正式建置輸出位於 `dist/`。

## 後端連線

前端預設使用目前網頁 hostname 與 port `18000` 連接 integration Compose 的
loopback Nginx gateway，再由 gateway 連接 Docker FastAPI。正式環境與預設設定
會忽略 URL query 的 backend／FHIR 端點覆寫，避免惡意連結改變病歷資料目的地。
只有本機開發需要臨時切換端點時，才可同時啟用開關並列出允許 origin：

```dotenv
VITE_ENABLE_BACKEND_QUERY_OVERRIDE=true
VITE_BACKEND_QUERY_OVERRIDE_ORIGINS=http://localhost:9000,http://192.168.1.20:9000
VITE_ENABLE_FHIR_QUERY_OVERRIDE=true
VITE_FHIR_QUERY_OVERRIDE_ORIGINS=http://localhost:8080
```

啟用後可使用：

```text
http://localhost:5173/?backendPort=9000#/
http://localhost:5173/?backend=http://192.168.1.20:9000#/
```

跨 origin backend 即使在 allowlist 內也不會攜帶 cookie；需要病患 session 的環境
應使用同源 reverse proxy。固定端點則由 `.env` 設定：

```bash
cp .env.example .env
```

```dotenv
VITE_BACKEND_PORT=18000
# 正式同源 reverse proxy 可改用：
# VITE_BACKEND_BASE_URL=/api
```

啟動完整 Docker backend pipeline：

```bash
cd integration-deployment
docker compose up -d --build
```

發生「無法連線到後端」時，先開啟 `http://127.0.0.1:18000/v1/health` 確認
Docker gateway 可達，再檢查 frontend 的 backend URL 設定。Port 18000 僅綁在
同一台主機的 loopback，不提供手機或其他電腦直接存取。

## 病患端與醫師端

病患端會收集自由主訴、FHIR 尚未提供的基本資料與病史，再依主訴進入胸痛、
頭痛或腹痛的逐題問卷。選擇題支援單選、複選、自由補充與正／背面人體疼痛位置標記；
病患頁不再顯示 AMIE 決策 trace。

醫師端可瀏覽、分頁及依姓名、問診編號或主訴搜尋病例；新 `questionnaire` 病例顯示
疼痛位置、問卷原始回答與 Gemini 生成且未經醫師確認的六段式 EMR／臨床決策草稿，
但不建立固定疾病表排名。舊 AMIE 病例仍相容顯示既有排名與分析。病例需經二次確認
才會永久刪除；問診編號 `00000` 是內建的假病人展示資料。

規則中心的實際治理與權限邏輯在後端，請見
[../backend/README.md](../backend/README.md#醫師端規則中心)。

## FHIR 直接連線（僅限開發／測試）

### SMART EHR Launcher

Vite 開發站可由 SMART Launcher 使用以下 Launch URL 啟動：

```text
http://127.0.0.1:5173/ai-consult/launch.html
```

SMART client ID 預設為本機 sandbox 的 `my_web_app`；若院方另行註冊，請在 `.env`
設定公開的 client identifier：

```dotenv
VITE_SMART_CLIENT_ID=my_web_app
```

Provider EHR Launch 必須提供 `iss` 與 `launch` query parameters。授權 callback 必須在
authorization server 精確註冊為同一 origin 的：

```text
http://127.0.0.1:5173/ai-consult/?smart=1
```

不要混用 `localhost`／`127.0.0.1`、不同 port 或 HTTP／HTTPS；OAuth state 存在同源
browser sessionStorage。遠端瀏覽器的 `127.0.0.1` 指向操作該瀏覽器的電腦，跨電腦測試
需改用可達的核准 HTTPS hostname。FHIR issuer 也必須能由瀏覽器到達，並允許 App
origin 的 CORS。

授權成功後，病患頁以 `fhirclient` 恢復 authorized client，取得 `Patient`、可用的
`Encounter` launch context 及分頁後的 `$everything` Bundle，再交給既有 FHIR prefill
映射。只會回傳 Patient／Bundle resources 與必要 context metadata；access token 不會
加入 prefill record。當前 scope 只有讀取權限，不支援把 AI 病歷寫回 FHIR。

### Identifier 直連測試

使用本機 HAPI Server 時，可在 `.env` 設定：

```dotenv
VITE_ENABLE_DIRECT_FHIR=true
VITE_FHIR_BASE_URL=http://localhost:8080/fhir
```

開始問診畫面可選擇兩種 `Patient.identifier` 查詢：

- 台灣身分證：`http://www.moi.gov.tw|A000000000`
- Synthea Default ID：
  `https://github.com/synthetichealth/synthea|c85baeef-9dbd-d06f-791d-5e1e3f24a8bf`

找到唯一病人後，前端使用 HAPI 回傳的 resource ID 讀取
`Patient/{id}/$everything`，再將資料映射至問卷預填。Synthea Default ID 只是
identifier value，不預設與 HAPI `Patient.id` 相同。HAPI 必須允許 Vite 開發網址的
CORS。

測試 Bundle 位於 `../backend/fhir_samples/`。身分證直接查詢只適用本機或受控
測試環境；正式環境必須使用 SMART on FHIR OAuth、最小權限 scope、核准的
client registration 與稽核。完整 SMART 流程請見
[../smart-app/README.md](../smart-app/README.md)。

## Avatar providers

病患端支援兩種可切換的 Avatar，預設為完全本地：

- `local`：Fun-CosyVoice3-0.5B-2512 + MuseTalk 1.5，由後端 GPU 服務產生。
- `did`：保留原本 D-ID Agent SDK；Client Key 與 Agent ID 可在設定面板輸入。

D-ID browser SDK 以鎖定版本的 `@d-id/client-sdk` npm dependency 隨應用建置，
並在選用 D-ID 時才從本地 JavaScript chunk 延遲載入；瀏覽器不會再向第三方 CDN
動態下載 SDK。

可在 `.env` 選擇預設 provider：

```dotenv
VITE_AVATAR_PROVIDER=local
VITE_DID_CLIENT_KEY=
VITE_DID_AGENT_ID=
```

頁面載入後會自動啟用預設 provider；失敗時仍可使用純文字輸入並在主舞台重試。
所有 `VITE_*` 值都會在 build-time
寫入公開的瀏覽器 JavaScript；因此建議在 UI 輸入 D-ID 資料（只存於頁面記憶體）。
若必須預先設定，只能使用由 [D-ID Studio](https://studio.d-id.com) 建立、限制部署
網域的瀏覽器／Embed Key，絕不可放伺服器私鑰。

醫師影像與朗讀字幕會在開始問診前及問診畫面上方優先顯示。每次 Avatar 播放
完成後會自動開啟麥克風；使用者開始說話後連續停頓 5 秒，錄音會自動交給
Breeze ASR。辨識文字回填輸入框後有 3 秒可直接編輯，任何編輯都會取消自動
送出；按下麥克風手動停止的錄音則不會自動送出。Avatar 設定可選國語或閩南語；
若 ASR 沒有辨識出內容，醫生會以目前語言請使用者再說一次。

## OpenAPI 型別

後端的版本控制規格位於 `../docs/openapi.json`。API model 或 route 變更後：

```bash
cd ../backend
python -m scripts.export_openapi
python -m scripts.export_openapi --check

cd ../frontend
npm run api:types
npm run api:check
```

請勿手動修改 `src/generated/api.d.ts`。
