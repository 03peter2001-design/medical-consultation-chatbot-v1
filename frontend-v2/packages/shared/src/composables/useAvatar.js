import { computed, onBeforeUnmount, ref } from 'vue'

let sdkPromise

async function loadDidSdk(timeout = 10000) {
  if (!sdkPromise) {
    sdkPromise = import('@d-id/client-sdk').catch((error) => {
      sdkPromise = undefined
      throw error
    })
  }

  return Promise.race([
    sdkPromise,
    new Promise((_, reject) => {
      window.setTimeout(
        () => reject(new Error('D-ID SDK 載入逾時')),
        timeout,
      )
    }),
  ])
}

export function normalizeAvatarProvider(value) {
  return String(value || '').trim().toLowerCase() === 'did' ? 'did' : 'local'
}

export function cleanSpeechText(text) {
  return text
    .replace(/【.*?】/g, '')
    .replace(/[（(][^）)]*[）)]/g, '')
    .replace(/^[a-zA-Z]\.\s?.*$/gm, '')
    .replace(/^選項[：:].*$/gm, '')
    .replace(/\n+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export function useAvatar({
  getStatus,
  synthesize,
  initialProvider = 'local',
} = {}) {
  const provider = ref(normalizeAvatarProvider(initialProvider))
  const manager = ref(null)
  const videoStream = ref(null)
  const videoUrl = ref('')
  const imageUrl = ref('/avatar/doctor.png')
  const connectionState = ref('idle')
  const status = ref('Avatar 尚未啟用')
  const statusTone = ref('idle')
  const talking = ref(false)
  const speechModel = ref('Fun-CosyVoice3-0.5B-2512')
  const animationModel = ref('MuseTalk 1.5')
  let speechQueue = Promise.resolve()
  let userEnabled = false
  let lifecycleToken = 0
  let activeRequestController = null

  const isLocal = computed(() => provider.value === 'local')
  const isDid = computed(() => provider.value === 'did')
  const isConnected = computed(() => connectionState.value === 'connected')
  const isConnecting = computed(() => connectionState.value === 'connecting')
  const providerLabel = computed(() => isDid.value ? 'D-ID' : '本地 Avatar')
  const headerStatus = computed(() => {
    if (talking.value) return `${providerLabel.value} 說話中`
    if (isConnecting.value) return `${providerLabel.value} 連線或生成中`
    if (isConnected.value) return `${providerLabel.value} 已啟用`
    return '文字問診模式'
  })
  const headerTone = computed(() => {
    if (talking.value) return 'talking'
    if (isConnected.value) return 'online'
    return 'idle'
  })

  function isCurrent(token, expectedProvider = provider.value) {
    return userEnabled && token === lifecycleToken && provider.value === expectedProvider
  }

  function revokeVideo() {
    if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
    videoUrl.value = ''
  }

  function resetConnection(message = 'Avatar 已停用；問診仍可繼續') {
    revokeVideo()
    videoStream.value = null
    connectionState.value = 'idle'
    talking.value = false
    status.value = message
    statusTone.value = 'idle'
  }

  async function connectLocal() {
    userEnabled = true
    const token = lifecycleToken
    if (isConnected.value) return true
    connectionState.value = 'connecting'
    status.value = '正在檢查本地模型服務…'
    statusTone.value = 'waiting'
    try {
      const info = await getStatus()
      if (!isCurrent(token, 'local')) return false
      speechModel.value = info.speech_model || speechModel.value
      animationModel.value = info.animation_model || animationModel.value
      if (!info.enabled || !info.available) {
        throw new Error('GPU 模型服務尚未就緒')
      }
      connectionState.value = 'connected'
      status.value = `本地 Avatar 已啟用（${info.device || 'local'}）`
      statusTone.value = 'success'
      return true
    } catch (error) {
      if (!isCurrent(token, 'local')) return false
      userEnabled = false
      resetConnection(`本地 Avatar 暫時不可用：${error.message}`)
      statusTone.value = 'error'
      return false
    }
  }

  async function connectDid({ clientKey = '', agentId = '' } = {}) {
    const normalizedKey = clientKey.trim()
    const normalizedAgentId = agentId.trim()
    if (!normalizedKey || !normalizedAgentId) {
      status.value = '請填入 D-ID Client Key 和 Agent ID'
      statusTone.value = 'error'
      return false
    }

    userEnabled = true
    const token = lifecycleToken
    if (isConnected.value) return true
    connectionState.value = 'connecting'
    status.value = 'D-ID SDK 載入中…'
    statusTone.value = 'waiting'

    let nextManager = null
    try {
      const sdk = await loadDidSdk()
      if (!isCurrent(token, 'did')) return false
      status.value = 'D-ID 連接中…'
      nextManager = await sdk.createAgentManager(normalizedAgentId, {
        auth: { type: 'key', clientKey: normalizedKey },
        callbacks: {
          onSrcObjectReady(stream) {
            if (isCurrent(token, 'did')) videoStream.value = stream
          },
          onConnectionStateChange(state) {
            if (!isCurrent(token, 'did')) return
            if (state === 'connected') {
              connectionState.value = 'connected'
              status.value = 'D-ID 已連線 ✓'
              statusTone.value = 'success'
            } else if (state === 'disconnected' || state === 'failed') {
              userEnabled = false
              resetConnection('D-ID 連線中斷；問診仍可繼續')
            }
          },
          onVideoStateChange(state) {
            if (isCurrent(token, 'did')) talking.value = state === 'PLAY'
          },
          onError() {
            if (!isCurrent(token, 'did')) return
            userEnabled = false
            resetConnection('D-ID 連接失敗；仍可使用純文字問診')
            statusTone.value = 'error'
          },
        },
      })
      if (!isCurrent(token, 'did')) {
        await nextManager.disconnect().catch(() => undefined)
        return false
      }
      manager.value = nextManager
      await nextManager.connect()
      return isCurrent(token, 'did')
    } catch (error) {
      manager.value = null
      await nextManager?.disconnect().catch(() => undefined)
      if (!isCurrent(token, 'did')) return false
      userEnabled = false
      resetConnection(`D-ID 連接失敗：${error.message}`)
      statusTone.value = 'error'
      return false
    }
  }

  async function connect(credentials = {}) {
    return isDid.value ? connectDid(credentials) : connectLocal()
  }

  async function disconnect(message = 'Avatar 已停用；問診仍可繼續') {
    userEnabled = false
    lifecycleToken += 1
    activeRequestController?.abort()
    activeRequestController = null
    const currentManager = manager.value
    manager.value = null
    if (currentManager) {
      try {
        await currentManager.disconnect()
      } catch {
        // Keep the rest of the consultation available after a provider failure.
      }
    }
    resetConnection(message)
  }

  async function setProvider(value) {
    const nextProvider = normalizeAvatarProvider(value)
    if (nextProvider === provider.value) return
    await disconnect()
    provider.value = nextProvider
    status.value = `${nextProvider === 'did' ? 'D-ID' : '本地 Avatar'} 尚未啟用`
  }

  async function performLocalSpeech(text, token) {
    if (!isCurrent(token, 'local')) return
    const input = cleanSpeechText(text)
    if (!input) return
    connectionState.value = 'connecting'
    status.value = 'CosyVoice3 與 MuseTalk 生成中…'
    statusTone.value = 'waiting'
    const controller = new AbortController()
    activeRequestController = controller
    try {
      const result = await synthesize(input, { signal: controller.signal })
      if (!isCurrent(token, 'local')) return
      revokeVideo()
      videoUrl.value = URL.createObjectURL(result.blob)
      speechModel.value = result.speechModel || speechModel.value
      animationModel.value = result.animationModel || animationModel.value
      connectionState.value = 'connected'
      status.value = result.cacheHit ? '影片已由本機快取載入' : '本地影片已完成'
      statusTone.value = 'success'
    } catch (error) {
      if (!isCurrent(token, 'local') || error?.name === 'AbortError') return
      connectionState.value = 'connected'
      talking.value = false
      status.value = `本次本地 Avatar 失敗：${error.message}`
      statusTone.value = 'error'
      console.warn('本地 Avatar 語音播放失敗：', error)
    } finally {
      if (activeRequestController === controller) activeRequestController = null
    }
  }

  function speak(text) {
    const input = cleanSpeechText(text)
    if (!input || !userEnabled || !isConnected.value) return Promise.resolve()
    if (isDid.value) {
      if (!manager.value) return Promise.resolve()
      return manager.value.speak({ type: 'text', input }).catch((error) => {
        console.warn('D-ID Avatar 語音播放失敗：', error)
      })
    }

    const token = lifecycleToken
    speechQueue = speechQueue
      .catch(() => undefined)
      .then(() => performLocalSpeech(input, token))
    return speechQueue
  }

  function onPlaybackStart() {
    if (isLocal.value) talking.value = true
  }

  function onPlaybackEnd() {
    if (isLocal.value) talking.value = false
  }

  function onPlaybackError() {
    if (!isLocal.value) return
    talking.value = false
    status.value = '影片無法自動播放，請使用播放器按鈕'
    statusTone.value = 'error'
  }

  onBeforeUnmount(() => {
    void disconnect()
  })

  return {
    connect,
    disconnect,
    setProvider,
    speak,
    onPlaybackStart,
    onPlaybackEnd,
    onPlaybackError,
    provider,
    providerLabel,
    isLocal,
    isDid,
    manager,
    videoStream,
    videoUrl,
    imageUrl,
    speechModel,
    animationModel,
    status,
    statusTone,
    talking,
    isConnected,
    isConnecting,
    headerStatus,
    headerTone,
  }
}
