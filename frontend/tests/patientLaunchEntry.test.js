import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'

// Execute the actual component setup against Vue's controlled v-model scheduler.
// The camera child and DOM rendering are irrelevant to the model timing regression.
const componentUrl = new URL('../src/components/PatientLaunchEntry.vue', import.meta.url)
const { descriptor } = parse(readFileSync(componentUrl, 'utf8'))
const compiled = compileScript(descriptor, { id: 'patient-launch-entry-test' }).content
  .replace("import QrCodeScanner from './QrCodeScanner.vue'", 'const QrCodeScanner = {}')
  .replace(/from (['"])([^'"]+)\1/g, (_match, _quote, specifier) => {
    const resolved = specifier.startsWith('.')
      ? new URL(specifier, componentUrl).href
      : import.meta.resolve(specifier)
    return `from ${JSON.stringify(resolved)}`
  })
const { default: PatientLaunchEntry } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)
PatientLaunchEntry.render = () => null

function mountEntry(initialCode = '') {
  const code = ref(initialCode)
  const redeeming = ref(false)
  const events = []
  const Parent = defineComponent({
    setup: () => () => h(PatientLaunchEntry, {
      modelValue: code.value,
      'onUpdate:modelValue': (value) => { code.value = value },
      redeeming: redeeming.value,
      onRedeem: (value) => { events.push(value) },
    }),
  })
  const renderer = createRenderer({
    createComment: () => ({}),
    insert() {},
    remove() {},
    parentNode: () => null,
    nextSibling: () => null,
  })
  const app = renderer.createApp(Parent)
  app.mount({})
  return {
    code, redeeming, events,
    state: app._instance.subTree.component.setupState,
    unmount: () => app.unmount(),
  }
}

const firstCode = 'Synthetic_first_0123456789_abcdefgh'
const secondCode = 'Synthetic_second_0123456789_abcdef'
// Shape-valid encrypted payload: the entry never decrypts it or calls the API.
const encryptedCode = ['bqr1', 16, 12, 48]
  .map((value) => typeof value === 'number' ? Buffer.alloc(value).toString('base64url') : value)
  .join('.')

test('raw scans redeem the newly scanned controlled model from empty and stale inputs', async () => {
  for (const initialCode of ['', firstCode]) {
    const entry = mountEntry(initialCode)
    try {
      await entry.state.acceptScan(secondCode)
      assert.equal(entry.code.value, secondCode)
      assert.deepEqual(entry.events, [{ code: secondCode, birthday: '' }])
    } finally {
      entry.unmount()
    }
  }
})

test('encrypted scans require a valid birthday and clear it after redeem or code replacement', async () => {
  const entry = mountEntry(firstCode)
  try {
    entry.state.birthday = '19991231'
    await entry.state.acceptScan(encryptedCode)
    assert.equal(entry.code.value, encryptedCode)
    assert.equal(entry.state.needsBirthday, true)
    assert.equal(entry.state.birthday, '')
    assert.deepEqual(entry.events, [])
    entry.state.redeem()
    assert.deepEqual(entry.events, [])
    entry.state.birthday = '20000230'
    entry.state.redeem()
    assert.deepEqual(entry.events, [])
    entry.state.birthday = '20000101'
    entry.redeeming.value = true
    await nextTick()
    entry.state.redeem()
    assert.deepEqual(entry.events, [])
    entry.redeeming.value = false
    await nextTick()
    entry.state.redeem()
    assert.deepEqual(entry.events, [{ code: encryptedCode, birthday: '20000101' }])
    assert.equal(entry.state.birthday, '')
    entry.state.birthday = '19991231'
    entry.code.value = secondCode
    await nextTick()
    assert.equal(entry.state.birthday, '')
  } finally {
    entry.unmount()
  }
})
