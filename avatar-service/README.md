# 本地語音與醫師 Avatar 服務

這個容器把問診系統的 AI 回覆轉成一段 MP4：

1. `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 在本機合成國語或臺灣閩南語語音。
2. 預設由 `TMElyralab/MuseTalk 1.5` 依 `pic/dr training pc.png` 產生 25 fps
   唇形；也可關閉動圖，只輸出同一醫師基準圖與語音的靜態 MP4。
3. 結果保存於 `avatar-cache` volume；相同文字會直接讀取快取。

服務只加入 Docker 私有網路，不發布 host port。病患瀏覽器透過已驗證的
FastAPI `/v1/avatar/*` 路由使用它。問診流程不依賴 Avatar；服務失效時仍可
使用文字問診。

## 服務版本

目前文件基線：**v1.2.0（2026-08-11）**。

此版本號是依 `devlog/2026-08-07.md` 回溯整理的 Avatar 服務文件基線，目前沒有
對應的 Git tag 或獨立 release，也不表示 Avatar、聲線、肖像或任何臨床內容已取得
臨床核准。後端 `/v1/avatar/*` 的 `/v1` 是 API 契約前綴，與本服務版本無關。

### v1.2.0 (2026-08-11)

- 新增向下相容的 `AVATAR_ANIMATION_ENABLED` 服務預設；預設 `true` 保留
  MuseTalk 唇形，設為 `false` 時仍以醫師基準圖與 CosyVoice 音訊快速產生靜態
  MP4。`/v1/synthesize` 與 `/v1/warmup` 也接受 optional `animation_enabled`
  boolean，讓本機 frontend／backend 流程可逐次覆寫，不必重建 Docker image。
- 靜態模式的模型檢查、預下載及 warm-up 只需要 CosyVoice，不下載、不載入也不
  呼叫 MuseTalk、VAE 或嘴型用 `whisper-tiny`；health 會回報
  `animation_enabled: false` 與 `animation_model: static-image mode`。
- 動態／靜態模式已納入影片 cache key，切換設定不會誤用另一模式先前產生的影片；
  相同模式與文字仍沿用既有 MP4 快取。此模式只改變呈現方式，不改寫問診內容或
  CosyVoice 語音，也不新增外部資料傳輸。

請求省略 `animation_enabled` 時會沿用服務預設，保持既有 client 相容：

```json
{"text":"請問哪裡不舒服？","language":"mandarin","animation_enabled":false}
```

warm-up 可用同一欄位只預載當次模式需要的模型；空 body 或省略欄位仍採服務預設：

```json
{"animation_enabled":true}
```

### v1.1.1（2026-08-10）

- 修正閩南語選項仍合成國語的問題：預設 instruction 改用目前固定版 CosyVoice3
  原始碼內建且受訓的精確控制詞 `请用闽南话表达`，不再使用模型可能忽略的自訂
  繁體長句。instruction 已包含在 cache key，升級後不會沿用先前錯誤的國語影片。
- 此控制只改變語音的方言發音，不把醫療文字交給額外翻譯模型，也不改寫畫面字幕
  或問診內容；因此不新增病患資料對外傳輸，也避免翻譯改變臨床語意。

### v1.1.0（2026-08-10）

- 合成請求新增 `mandarin`／`minnan` 語言選擇，分別套用台灣國語與臺灣閩南語
  CosyVoice3 instruction；語言與 instruction 都納入 cache key，避免跨語言誤用影片。
- 新增 `/v1/warmup`，一次載入 CosyVoice3、MuseTalk、VAE 與嘴型音訊 encoder；
  預設合成後保留模型，避免每句回覆重新載入。
- 移除原本把下半張臉矩形直接貼回原圖的融合方式，改為只覆蓋嘴部／下半臉中央、
  四周 alpha 歸零的橢圓羽化遮罩，保留頭髮、臉頰邊界、下巴外緣、頸部與衣領原圖。
- 在 RTX 5060 Ti 16 GB 上與 Breeze ASR 同時 warm-up 後，兩次連續合成仍維持所有
  模型 loaded；國語與閩南語影片皆成功輸出，且抽幀不再出現矩形水平接縫。

### v1.0.0（2026-08-07）

- 建立私有網路內的本機 Avatar 服務：以 CosyVoice3 合成華語語音，再由 MuseTalk
  1.5 依指定醫師圖產生 25 fps MP4；問診不依賴 Avatar，失效時仍可使用文字流程。
- 以內容 hash 快取完成影片，模型權重與影片分別保存於持久 volume；提供模型預下載、
  狀態檢查及快取重用機制，避免相同文字重複推論。
- 固定 CosyVoice 與 MuseTalk 上游 source revision；CosyVoice speech-tokenizer 的
  ONNX 前處理固定走 CPU，語音主模型及唇形生成使用 CUDA／FP16。
- 支援唇形生成失敗時保留合成語音與靜態圖片的 fallback；後端 gateway 沿用病患
  session，且不向瀏覽器暴露 Avatar service host。
- 加入分階段 VRAM 釋放：語音完成後卸載 CosyVoice，影片完成或失敗後卸載
  MuseTalk 並清除 CUDA cache，以支援與 Breeze ASR 共用單張 16 GB GPU。
- 模型與媒體只在本機服務及 volumes 間處理，不送往第三方 Avatar provider；真人
  肖像與聲音在使用前仍須取得明確同意，Avatar 不代表醫師本人遠距看診或診斷。

## 模型與執行環境

Docker image 固定使用下列官方原始碼 revision，以免上游更新未經驗證就進入
部署：

- [QwenAudio/CosyVoice](https://github.com/QwenAudio/CosyVoice) `074ca6d`
- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk) `0a89dec`

兩個專案的程式碼分別使用 Apache-2.0 與 MIT 授權；實際部署前仍應依組織政策
審閱模型卡、權重與所有間接依賴的授權。模型權重第一次使用時才從 Hugging
Face 下載，之後全部從 `avatar-models` volume 讀取；推論期間不會把文字、語音
或影像送到第三方 Avatar 服務。

容器內的 `openai-whisper` 套件只供 CosyVoice 擷取參考聲音特徵；啟用動圖時，
MuseTalk 的 `whisper-tiny` 權重則只把已合成的語音編碼成嘴型條件。兩者都不執行
語音轉文字，也不會另建 ASR 服務；病患語音辨識仍使用系統既有的 Breeze ASR。

為避開 Blackwell 顯示卡上 ONNX Runtime 的 PTX 相容性問題，CosyVoice 的小型
speech-tokenizer ONNX 前處理固定走 CPU；CosyVoice3 語音主模型及 MuseTalk
仍以 CUDA/FP16 推論。

建議先預下載，讓正式病患不必承擔第一次下載時間：

```sh
cd integration-deployment
docker compose build avatar
docker compose run --rm avatar python3.10 -m app.download_models
```

上述 CLI 下載命令會依服務的 `AVATAR_ANIMATION_ENABLED` 預設判斷所需模型；
`false` 時只下載 CosyVoice，不下載 MuseTalk、VAE 或嘴型用 `whisper-tiny`。
若服務預設為靜態，但 `/v1/warmup` 當次傳入 `animation_enabled: true`，則會下載
並載入動圖所需模型；反向覆寫為 `false` 時只檢查及載入 CosyVoice。

## 說話人與肖像

預設 zero-shot 參考音來自 CosyVoice 官方 repository，只作為可運作的初始聲線。
正式使用應改成已取得同意的 3–10 秒單人、乾淨、無背景音 WAV，並以 Compose
override 掛入容器：

```yaml
services:
  avatar:
    environment:
      COSYVOICE_PROMPT_WAV: /run/secrets/avatar-voice-prompt.wav
    volumes:
      - ./secrets/avatar-voice-prompt.wav:/run/secrets/avatar-voice-prompt.wav:ro
```

使用真人肖像及聲音前，必須取得當事人對合成用途、使用範圍與保存期限的明確
同意。此 Avatar 是介面呈現，不是醫師本人遠距看診，也不應用來暗示已做出診斷。

## 調校

- `MUSETALK_FACE_BBOX=585,140,915,520` 是原始 1536×1024 圖片上的人臉框。
- `AVATAR_ANIMATION_ENABLED=true` 啟用 MuseTalk 動態唇形；設為 `false` 時完全
  略過 MuseTalk 模型檢查、下載、warm-up 與推論，只輸出基準圖加語音的靜態 MP4。
  此值是請求省略 `animation_enabled` 時的預設，不限制 client 逐次覆寫。
- `AVATAR_OUTPUT_WIDTH=768` 控制影片寬度；降低可節省延遲與儲存空間。
- `MUSETALK_BATCH_SIZE=8` 可依顯示卡記憶體調整；OOM 時先降為 `4` 或 `2`。
- `AVATAR_REQUIRE_CUDA=true` 避免正式環境意外以極慢的 CPU 跑 MuseTalk。
- `AVATAR_STATIC_FALLBACK=true` 只在唇形階段出錯時保留 CosyVoice 語音與靜態圖。
- `AVATAR_RELEASE_GPU_AFTER_RENDER=false` 讓 warm-up 後的 CosyVoice 與 MuseTalk
  常駐，避免每段回覆重新載入；容量不足的 GPU 可設為 `true` 回退分階段釋放。

目前的 Breeze ASR、CosyVoice3 與 MuseTalk 共用同一張 GPU。本專案在 16 GB
RTX 5060 Ti 實測全部常駐約使用 11.5 GB，尚餘約 4.3 GB；不同驅動、batch、模型
revision 或並行流量都可能提高峰值。若 OOM，先把兩個 release 設定改回 `true`，
再降低 MuseTalk batch，或把 ASR／Avatar 指定到不同 GPU。
