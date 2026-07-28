import { computed, onBeforeUnmount, ref } from 'vue'

const DID_SDK_URL = 'https://esm.sh/@d-id/client-sdk@1'
let sdkPromise

async function loadDidSdk(timeout = 10000) {
  if (!sdkPromise) {
    sdkPromise = import(/* @vite-ignore */ DID_SDK_URL).catch((error) => {
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

function cleanSpeechText(text) {
  return text
    .replace(/【.*?】/g, '')
    .replace(/[（(][^）)]*[）)]/g, '')
    .replace(/^[a-zA-Z]\.\s?.*$/gm, '')
    .replace(/^選項[：:].*$/gm, '')
    .replace(/\n+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export function useAvatar() {
  const manager = ref(null)
  const videoStream = ref(null)
  const connectionState = ref('idle')
  const status = ref('未設定時使用純對話模式')
  const statusTone = ref('idle')
  const talking = ref(false)

  const isConnected = computed(() => connectionState.value === 'connected')
  const isConnecting = computed(() => connectionState.value === 'connecting')
  const headerStatus = computed(() => {
    if (talking.value) return 'Avatar 說話中'
    if (isConnected.value) return 'Avatar 已連線'
    return '純對話模式'
  })
  const headerTone = computed(() => {
    if (talking.value) return 'talking'
    if (isConnected.value) return 'online'
    return 'idle'
  })

  function resetConnection(message = 'Avatar 已中斷；問診仍可繼續') {
    manager.value = null
    videoStream.value = null
    connectionState.value = 'idle'
    talking.value = false
    status.value = message
    statusTone.value = 'idle'
  }

  async function connect({ clientKey, agentId }) {
    if (!clientKey.trim() || !agentId.trim()) {
      status.value = '請填入 Client Key 和 Agent ID'
      statusTone.value = 'error'
      return false
    }

    connectionState.value = 'connecting'
    status.value = 'SDK 載入中...'
    statusTone.value = 'waiting'

    try {
      const sdk = await loadDidSdk()
      status.value = '連接中...'
      const nextManager = await sdk.createAgentManager(agentId.trim(), {
        auth: { type: 'key', clientKey: clientKey.trim() },
        callbacks: {
          onSrcObjectReady(stream) {
            videoStream.value = stream
          },
          onConnectionStateChange(state) {
            if (state === 'connected') {
              connectionState.value = 'connected'
              status.value = '已連線 ✓'
              statusTone.value = 'success'
            } else if (state === 'disconnected' || state === 'failed') {
              resetConnection('Avatar 連線中斷；問診仍可繼續')
            }
          },
          onVideoStateChange(state) {
            talking.value = state === 'PLAY'
          },
          onError() {
            resetConnection('Avatar 連接失敗；仍可使用純對話問診')
            statusTone.value = 'error'
          },
        },
      })
      manager.value = nextManager
      await nextManager.connect()
      return true
    } catch {
      resetConnection('Avatar 連接失敗；仍可使用純對話問診')
      statusTone.value = 'error'
      return false
    }
  }

  async function disconnect() {
    const currentManager = manager.value
    if (currentManager) {
      try {
        await currentManager.disconnect()
      } catch {
        // The dialog must remain available even when D-ID disconnect fails.
      }
    }
    resetConnection()
  }

  async function speak(text) {
    if (!manager.value) return
    const input = cleanSpeechText(text)
    if (!input) return
    try {
      await manager.value.speak({ type: 'text', input })
    } catch (error) {
      console.warn('Avatar 語音播放失敗：', error)
    }
  }

  onBeforeUnmount(() => {
    void disconnect()
  })

  return {
    connect,
    disconnect,
    speak,
    videoStream,
    status,
    statusTone,
    talking,
    isConnected,
    isConnecting,
    headerStatus,
    headerTone,
  }
}
