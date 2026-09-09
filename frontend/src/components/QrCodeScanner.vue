<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  cameraAccessErrorMessage,
  launchCodeFromScan,
} from '../services/patientLaunch.js'

const emit = defineEmits(['scan', 'close'])

const video = ref(null)
const status = ref('正在啟用相機…')
const active = ref(false)
let stream = null
let detector = null
let scanTimer = null
let zxingControls = null
let delivered = false
let stopped = false

const cameraConstraints = {
  video: { facingMode: { ideal: 'environment' } },
  audio: false,
}

function stopScanner() {
  stopped = true
  active.value = false
  if (scanTimer) window.clearTimeout(scanTimer)
  scanTimer = null
  zxingControls?.stop()
  zxingControls = null
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
  if (video.value) video.value.srcObject = null
}

function acceptResult(rawValue, callbackControls = null) {
  const code = launchCodeFromScan(rawValue)
  if (!code || delivered) return false
  delivered = true
  if (callbackControls && !zxingControls) {
    callbackControls.stop?.()
  }
  stopScanner()
  emit('scan', code)
  return true
}

function closeScanner() {
  stopScanner()
  emit('close')
}

async function scanFrame() {
  if (!active.value || !video.value || !detector) return
  try {
    const results = await detector.detect(video.value)
    const code = results
      .map((result) => launchCodeFromScan(result.rawValue))
      .find(Boolean)
    if (code && acceptResult(code)) return
    status.value = results.length
      ? '已讀到 QR，但不是有效的問診 code。請對準完整 QR。'
      : '請將 QR code 放入框內。'
  } catch {
    status.value = '暫時無法辨識畫面，請保持 QR 清楚並重新對焦。'
  }
  if (active.value) scanTimer = window.setTimeout(scanFrame, 250)
}

async function startNativeScanner() {
  const supported = await window.BarcodeDetector.getSupportedFormats?.()
  if (supported && !supported.includes('qr_code')) return false
  detector = new window.BarcodeDetector({ formats: ['qr_code'] })
  stream = await navigator.mediaDevices.getUserMedia(cameraConstraints)
  if (stopped) {
    stream.getTracks().forEach((track) => track.stop())
    stream = null
    return true
  }
  active.value = true
  await nextTick()
  video.value.srcObject = stream
  await video.value.play()
  status.value = '請將 QR code 放入框內。'
  void scanFrame()
  return true
}

async function startZxingScanner() {
  status.value = '正在載入跨瀏覽器 QR 掃描器…'
  const { BrowserQRCodeReader } = await import('@zxing/browser')
  if (stopped) return
  await nextTick()
  const reader = new BrowserQRCodeReader(undefined, {
    delayBetweenScanAttempts: 250,
    delayBetweenScanSuccess: 500,
  })
  zxingControls = await reader.decodeFromConstraints(
    cameraConstraints,
    video.value,
    (result, _error, controls) => {
      if (!result || stopped) return
      if (!acceptResult(result.getText(), controls)) {
        status.value = '已讀到 QR，但不是有效的問診 code。請對準完整 QR。'
      }
    },
  )
  if (stopped) {
    zxingControls?.stop()
    zxingControls = null
    return
  }
  active.value = true
  status.value = '請將 QR code 放入框內。'
}

async function startScanner() {
  delivered = false
  stopped = false
  if (!window.isSecureContext) {
    status.value = cameraAccessErrorMessage(null, false)
    return
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    status.value = '此瀏覽器無法使用相機 API，請改用下方貼上 code。'
    return
  }
  try {
    if (window.BarcodeDetector) {
      try {
        if (await startNativeScanner()) return
      } catch (error) {
        if (
          ['NotAllowedError', 'SecurityError', 'NotFoundError', 'NotReadableError']
            .includes(String(error?.name || ''))
        ) {
          throw error
        }
        stopScanner()
        stopped = false
        status.value = '原生掃描器不可用，正在切換跨瀏覽器掃描器…'
      }
    }
    await startZxingScanner()
  } catch (error) {
    stopScanner()
    status.value = cameraAccessErrorMessage(error, window.isSecureContext)
  }
}

onBeforeUnmount(stopScanner)
onMounted(() => { void startScanner() })
</script>

<template>
  <div class="qr-scanner" role="dialog" aria-modal="true" aria-label="掃描問診 QR code">
    <div class="scanner-frame">
      <video ref="video" muted playsinline aria-label="QR 掃描相機畫面" />
      <span v-if="active" class="scanner-guide" aria-hidden="true" />
    </div>
    <p role="status">{{ status }}</p>
    <button type="button" @click="closeScanner">關閉相機，改用貼碼</button>
  </div>
</template>

<style scoped>
.qr-scanner {
  display: grid;
  width: min(100%, 420px);
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface-1);
}

.scanner-frame {
  position: relative;
  overflow: hidden;
  min-height: 220px;
  border-radius: 10px;
  background: #10232d;
}

.scanner-frame video {
  width: 100%;
  height: 260px;
  object-fit: cover;
}

.scanner-guide {
  position: absolute;
  inset: 14% 18%;
  border: 3px solid white;
  border-radius: 14px;
  box-shadow: 0 0 0 999px rgb(0 0 0 / 28%);
}

.qr-scanner p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.qr-scanner button {
  min-height: 42px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text);
  cursor: pointer;
}
</style>
