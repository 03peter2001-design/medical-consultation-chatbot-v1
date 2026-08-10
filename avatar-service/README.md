# 本地語音與醫師 Avatar 服務

這個容器把問診系統的 AI 回覆轉成一段 MP4：

1. `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 在本機合成華語語音。
2. `TMElyralab/MuseTalk 1.5` 依 `pic/dr training pc.png` 產生 25 fps 唇形。
3. 結果保存於 `avatar-cache` volume；相同文字會直接讀取快取。

服務只加入 Docker 私有網路，不發布 host port。病患瀏覽器透過已驗證的
FastAPI `/v1/avatar/*` 路由使用它。問診流程不依賴 Avatar；服務失效時仍可
使用文字問診。

## 服務版本

目前文件基線：**v1.0.0（2026-08-07）**。

此版本號是依 `devlog/2026-08-07.md` 回溯整理的 Avatar 服務文件基線，目前沒有
對應的 Git tag 或獨立 release，也不表示 Avatar、聲線、肖像或任何臨床內容已取得
臨床核准。後端 `/v1/avatar/*` 的 `/v1` 是 API 契約前綴，與本服務版本無關。

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

容器內的 `openai-whisper` 套件只供 CosyVoice 擷取參考聲音特徵；MuseTalk 的
`whisper-tiny` 權重則只把已合成的語音編碼成嘴型條件。兩者都不執行語音轉文字，
也不會另建 ASR 服務；病患語音辨識仍使用系統既有的 Breeze ASR。

為避開 Blackwell 顯示卡上 ONNX Runtime 的 PTX 相容性問題，CosyVoice 的小型
speech-tokenizer ONNX 前處理固定走 CPU；CosyVoice3 語音主模型及 MuseTalk
仍以 CUDA/FP16 推論。

建議先預下載，讓正式病患不必承擔第一次下載時間：

```sh
cd integration-deployment
docker compose build avatar
docker compose run --rm avatar python3.10 -m app.download_models
```

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
- `AVATAR_OUTPUT_WIDTH=768` 控制影片寬度；降低可節省延遲與儲存空間。
- `MUSETALK_BATCH_SIZE=8` 可依顯示卡記憶體調整；OOM 時先降為 `4` 或 `2`。
- `AVATAR_REQUIRE_CUDA=true` 避免正式環境意外以極慢的 CPU 跑 MuseTalk。
- `AVATAR_STATIC_FALLBACK=true` 只在唇形階段出錯時保留 CosyVoice 語音與靜態圖。
- `AVATAR_RELEASE_GPU_AFTER_RENDER=true` 會在語音完成後先卸載 CosyVoice，影片
  完成或失敗後再卸載 MuseTalk 並清除 CUDA cache。這會增加下一個未命中快取
  請求的模型重載延遲，但相同文字的 MP4 快取命中不載入模型。

目前的 Breeze ASR、CosyVoice3 與 MuseTalk 共用同一張 GPU。16 GB 部署預設啟用
上述分階段釋放策略；health 的 `speech_loaded` 與 `animation_loaded` 在請求期間
可能短暫為 `true`，完成後會回到 `false`。若仍 OOM，優先降低 MuseTalk batch，
再考慮把 ASR 或 Avatar 指定到不同 GPU。只有在 Avatar 獨占顯卡、且可接受模型
長時間佔用顯存時，才建議把此開關設為 `false` 來換取較低的重載延遲。
