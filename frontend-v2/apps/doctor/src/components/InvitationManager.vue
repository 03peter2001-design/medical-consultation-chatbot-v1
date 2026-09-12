<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import QRCode from 'qrcode'
import { api } from '@medical/shared/services/doctorBackend.js'
import { invitationStatuses, useInvitations } from '../invitations.js'

defineProps({ canManage: Boolean })
const emit = defineEmits(['changed'])
const {
  items, total, status, offset, loading, busy, error, issued, notice,
  limit, load, act, hasNext, dispose,
} = useInvitations(api)
const pending = ref(null)
const confirmation = ref(null)
const issuedPanel = ref(null)
const qr = ref('')
const copyMessage = ref('')
let qrVersion = 0

function date(value) {
  return value ? new Date(value).toLocaleString('zh-TW', { hour12: false }) : '—'
}

async function confirmAction() {
  const selection = pending.value
  if (!selection) return
  pending.value = null
  emit('changed')
  await act(selection.action, selection.row)
}

async function copy() {
  try {
    await navigator.clipboard.writeText(issued.value.public_url)
    copyMessage.value = '連結已複製'
  } catch {
    copyMessage.value = '無法自動複製，請選取下方連結手動複製。'
  }
}

watch(issued, async (value) => {
  const version = ++qrVersion
  qr.value = ''
  copyMessage.value = ''
  if (!value?.public_url) return
  await nextTick()
  issuedPanel.value?.focus()
  try {
    const image = await QRCode.toDataURL(value.public_url, { width: 224, margin: 2 })
    if (version === qrVersion) qr.value = image
  } catch {
    if (version === qrVersion) copyMessage.value = 'QR 圖片產生失敗，仍可複製邀請連結。'
  }
})
watch(pending, async (value) => {
  if (!value) return
  await nextTick()
  confirmation.value?.focus()
})
watch(status, () => { pending.value = null; void load(0) })
onMounted(() => load(0))
onBeforeUnmount(() => { dispose(); qrVersion += 1 })
</script>

<template>
  <section class="invitation-manager" aria-labelledby="invitation-heading" :aria-busy="loading || busy">
    <div class="manager-toolbar">
      <div>
        <h2 id="invitation-heading">QR Code 派發管理</h2>
        <p>本院所全部邀請紀錄。已兌換代表開啟邀請，不代表完成問診。</p>
      </div>
      <label>使用狀態
        <select v-model="status" :disabled="busy">
          <option value="">全部狀態</option>
          <option v-for="(label, key) in invitationStatuses" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <button type="button" :disabled="loading || busy" @click="pending = null; load(0)">重新整理</button>
    </div>
    <p v-if="!canManage" class="hint">目前僅可查看；取消與重新派發需要院方授予邀請管理權限。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div v-if="pending" ref="confirmation" class="confirmation" role="alert" tabindex="-1">
      <p><strong>{{ pending.action === 'cancel' ? '取消邀請' : '重新派發' }}：就診 {{ pending.row.reg_sno }}</strong></p>
      <p>舊 QR Code 與已兌換的病人工作階段會失效。{{ pending.action === 'reissue' ? '新碼會沿用此筆邀請的病人與就診資料，重新開始問診。' : '尚未完成的問診將無法繼續。' }}</p>
      <button type="button" @click="confirmAction">確認{{ pending.action === 'cancel' ? '取消邀請' : '重新派發' }}</button>
      <button type="button" @click="pending = null">返回</button>
    </div>
    <div v-if="issued" ref="issuedPanel" class="issued" role="status" tabindex="-1">
      <img v-if="qr" :src="qr" alt="重新派發的患者問診 QR Code" width="224" height="224" />
      <div>
        <strong>新的患者問診邀請</strong>
        <p>有效期限：{{ date(issued.expires_at) }}</p>
        <p>請立即複製或交付；關閉或重新整理後不會再次顯示此碼。</p>
        <a :href="issued.public_url" target="_blank" rel="noopener noreferrer">{{ issued.public_url }}</a>
        <div class="actions"><button type="button" @click="copy">複製新連結</button><button type="button" @click="issued = null; notice = ''">關閉新碼</button></div>
        <p v-if="copyMessage">{{ copyMessage }}</p>
      </div>
    </div>
    <p v-if="loading" role="status">正在讀取派發紀錄…</p>
    <p v-else-if="!items.length && !error">目前沒有符合條件的邀請。</p>
    <div v-else-if="items.length" class="table-scroll" tabindex="0" aria-label="QR Code 邀請清單">
      <table>
        <thead><tr><th>病人／就診識別碼</th><th>使用狀態</th><th>派發／到期時間</th><th>兌換／最近活動</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in items" :key="row.invite_id">
            <td><strong>{{ row.patient_sno }}</strong><small>就診 {{ row.reg_sno }}</small><small class="reference">{{ row.invite_id }}</small></td>
            <td><span class="status" :class="row.status">{{ invitationStatuses[row.status] || '未知狀態' }}</span><small v-if="row.consultation_id">問診 {{ row.consultation_id }}</small><small v-if="row.replaced_by_invite_id">已重新派發</small></td>
            <td>{{ date(row.created_at) }}<small>到期 {{ date(row.expires_at) }}</small></td>
            <td>{{ date(row.consumed_at) }}<small>活動 {{ date(row.last_seen_at) }}</small><small v-if="row.session_expires_at">工作階段到期 {{ date(row.session_expires_at) }}</small></td>
            <td><div class="actions">
              <button type="button" :disabled="!canManage || busy || loading || !['active', 'consumed'].includes(row.status)" @click="pending = { action: 'cancel', row }">取消邀請</button>
              <button type="button" :disabled="!canManage || busy || loading || !['active', 'consumed', 'expired', 'revoked'].includes(row.status) || !!row.replaced_by_invite_id" @click="pending = { action: 'reissue', row }">重新派發</button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <nav class="pagination" aria-label="邀請清單分頁">
      <span>{{ loading ? '讀取中' : `共 ${total} 筆${items.length ? `，顯示 ${offset + 1}–${offset + items.length}` : ''}` }}</span>
      <button type="button" :disabled="loading || busy || offset === 0" @click="pending = null; load(offset - limit)">上一頁</button>
      <button type="button" :disabled="loading || busy || !hasNext || !!error" @click="pending = null; load(offset + limit)">下一頁</button>
    </nav>
  </section>
</template>

<style scoped>
.invitation-manager { margin: 0 0 18px; padding: 20px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-1); }
.manager-toolbar, .pagination, .actions, .issued { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.manager-toolbar > div { flex: 1; min-width: 240px; }
h2 { font-size: 19px; margin: 0 0 6px; }
p, small { font-size: 13px; line-height: 1.6; }
p { margin: 6px 0; }
.manager-toolbar p, small, .hint { color: var(--muted); }
label { display: flex; align-items: center; gap: 8px; font-size: 13px; }
button, select { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1); color: var(--text); font: inherit; font-size: 13px; }
button { cursor: pointer; }
button:disabled { opacity: .45; cursor: not-allowed; }
button:focus-visible, select:focus-visible, .table-scroll:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.table-scroll { overflow-x: auto; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
th, td { padding: 12px 10px; border-bottom: 1px solid var(--border); vertical-align: top; min-width: 130px; }
th { color: var(--muted); font-weight: 500; white-space: nowrap; }
small { display: block; }
.reference { max-width: 180px; overflow-wrap: anywhere; font-size: 11px; }
.status { display: inline-block; padding: 3px 9px; border-radius: 20px; background: var(--bg); white-space: nowrap; }
.active, .completed { color: #166534; background: #edf9f0; }
.consumed { color: #1e40af; background: #eff6ff; }
.revoked, .expired { color: #92400e; background: #fff7ed; }
.error { color: var(--danger); }
.confirmation { padding: 14px; margin: 12px 0; border: 1px solid #d69d44; border-radius: 8px; }
.confirmation button { margin: 8px 8px 0 0; }
.issued { padding: 16px; margin-top: 16px; background: var(--bg); border-radius: 8px; }
.issued > div { flex: 1; min-width: 0; }
.issued a { display: block; overflow-wrap: anywhere; color: var(--blue); margin: 10px 0; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.pagination span { margin-right: auto; font-size: 13px; }
@media (max-width: 600px) { .invitation-manager { padding: 12px; } .issued { flex-direction: column; align-items: stretch; } .issued img { align-self: center; } }
</style>
