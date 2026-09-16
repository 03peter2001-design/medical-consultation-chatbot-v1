import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const root = path.resolve(import.meta.dirname, '..')
const doctorRoot = path.join(root, 'apps', 'doctor')

test('doctor app exposes a configurable SMART EHR launch entry', async () => {
  const [html, entry, config, envExample, app, sharedSmart] = await Promise.all([
    readFile(path.join(doctorRoot, 'launch.html'), 'utf8'),
    readFile(path.join(doctorRoot, 'src/smartLaunchEntry.js'), 'utf8'),
    readFile(path.join(doctorRoot, 'vite.config.js'), 'utf8'),
    readFile(path.join(doctorRoot, '.env.example'), 'utf8'),
    readFile(path.join(doctorRoot, 'src/App.vue'), 'utf8'),
    readFile(path.join(root, 'packages/shared/src/services/smart.js'), 'utf8'),
  ])

  assert.match(html, /src="\/src\/smartLaunchEntry\.js"/)
  assert.match(html, /box-sizing:\s*border-box/)
  assert.match(html, /width:\s*min\(480px, calc\(100% - 32px\)\)/)
  assert.match(entry, /authorizeSmartEhrLaunch/)
  assert.match(entry, /ensureSmartClientLibrary/)
  assert.match(entry, /clientId: import\.meta\.env\.VITE_SMART_CLIENT_ID/)
  assert.match(entry, /scopes: import\.meta\.env\.VITE_SMART_SCOPES/)
  assert.match(entry, /issuerAllowlist: import\.meta\.env\.VITE_SMART_ISSUER_ALLOWLIST/)
  assert.match(entry, /allowInsecureLoopback: import\.meta\.env\.DEV/)
  assert.match(entry, /basePath: import\.meta\.env\.BASE_URL/)
  assert.match(entry, /無法連接 SMART 授權服務/)
  assert.doesNotMatch(entry, /initializeSmartPatient|readSmartPatientRecord|patient\//)

  assert.match(config, /input:\s*\{[\s\S]*launch:/)
  assert.match(config, /index:\s*fileURLToPath\(new URL\('index\.html'/)
  assert.match(config, /new URL\('launch\.html'/)
  for (const name of [
    'VITE_SMART_CLIENT_ID',
    'VITE_SMART_SCOPES',
    'VITE_SMART_ISSUER_ALLOWLIST',
  ]) {
    assert.match(config, new RegExp(`import\\.meta\\.env\\.${name}`))
    assert.match(envExample, new RegExp(`^${name}=`, 'm'))
  }

  assert.match(sharedSmart, /pkceMode:\s*['"]required['"]/)
  assert.match(app, /await doctorSession\.start\(\)/)
  assert.doesNotMatch(app, /initializeSmartPatient|readSmartPatientRecord/)
  assert.doesNotMatch(entry, /regSno|localStorage|local principal/i)
})

test('doctor production build emits the SMART launch page when built', async (t) => {
  const output = path.join(doctorRoot, 'dist', 'launch.html')
  try {
    await access(output)
  } catch {
    return t.skip('run the Doctor production build before inspecting the artifact')
  }
  const html = await readFile(output, 'utf8')
  assert.match(html, /SMART/)
  assert.match(html, /<script[^>]+type="module"/)

  const indexHtml = await readFile(
    path.join(doctorRoot, 'dist', 'index.html'),
    'utf8',
  )
  assert.match(
    indexHtml,
    /assets\/index-[A-Za-z0-9_-]+\.js/,
    'the existing eHIS deploy script extracts this entry name for cache busting',
  )
})
