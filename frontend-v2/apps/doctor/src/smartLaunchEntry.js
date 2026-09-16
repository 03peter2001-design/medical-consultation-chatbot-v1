import {
  authorizeSmartEhrLaunch,
  ensureSmartClientLibrary,
} from '@medical/shared/services/smart.js'

const status = document.querySelector('[data-smart-launch-status]')
const heading = document.querySelector('[data-smart-launch-heading]')

function showFailure(error) {
  document.body.dataset.launchState = 'error'
  if (heading) heading.textContent = '無法連接 SMART 授權服務'
  if (status) {
    status.textContent = `無法啟動 SMART 授權：${
      error instanceof Error ? error.message : '未知錯誤'
    }`
  }
}

async function startSmartLaunch() {
  const fhirLibrary = await ensureSmartClientLibrary()
  await authorizeSmartEhrLaunch({
    fhirLibrary,
    clientId: import.meta.env.VITE_SMART_CLIENT_ID,
    scopes: import.meta.env.VITE_SMART_SCOPES,
    issuerAllowlist: import.meta.env.VITE_SMART_ISSUER_ALLOWLIST,
    allowInsecureLoopback: import.meta.env.DEV,
    basePath: import.meta.env.BASE_URL,
  })
}

startSmartLaunch().catch(showFailure)
