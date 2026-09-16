import FHIR from 'fhirclient'

import {
  SMART_DOCTOR_QR_MODE,
  authorizeSmartEhrLaunch,
} from './services/smart.js'

const status = document.querySelector('[data-smart-launch-status]')

function showFailure(error) {
  document.body.dataset.launchState = 'error'
  if (status) {
    status.textContent = `無法啟動 SMART 授權：${
      error instanceof Error ? error.message : '未知錯誤'
    }`
  }
}

authorizeSmartEhrLaunch({
  fhirLibrary: FHIR,
  clientId: import.meta.env.VITE_SMART_CLIENT_ID || 'my_web_app',
  scopes: import.meta.env.VITE_SMART_SCOPES,
  issuerAllowlist: import.meta.env.VITE_SMART_ISSUER_ALLOWLIST,
  allowInsecureLoopback: import.meta.env.DEV,
  basePath: import.meta.env.BASE_URL,
  callbackMode: SMART_DOCTOR_QR_MODE,
}).catch(showFailure)
