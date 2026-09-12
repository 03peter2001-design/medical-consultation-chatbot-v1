import { computed, ref } from 'vue'

export const invitationStatuses = {
  active: '待使用', consumed: '已兌換', completed: '已完成',
  expired: '已過期', revoked: '已取消',
}

export function useInvitations(api) {
  const items = ref([])
  const total = ref(0)
  const status = ref('')
  const offset = ref(0)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const issued = ref(null)
  const notice = ref('')
  const limit = 20
  let requestVersion = 0
  let disposed = false

  async function load(nextOffset = offset.value) {
    const version = ++requestVersion
    loading.value = true
    error.value = ''
    notice.value = ''
    issued.value = null
    items.value = []
    try {
      const result = await api.listInvitations({ status: status.value, offset: nextOffset, limit })
      if (disposed || version !== requestVersion) return
      items.value = result.items
      total.value = result.total
      offset.value = nextOffset
    } catch (failure) {
      if (!disposed && version === requestVersion) error.value = `無法載入邀請：${failure.message}`
    } finally {
      if (!disposed && version === requestVersion) loading.value = false
    }
  }

  async function act(action, row) {
    if (busy.value || loading.value || !['cancel', 'reissue'].includes(action)) return false
    busy.value = true
    error.value = ''
    notice.value = ''
    issued.value = null
    let success = false
    try {
      const result = action === 'cancel'
        ? await api.cancelInvitation(row.invite_id)
        : await api.reissueInvitation(row.invite_id)
      if (disposed) return false
      success = true
      await load(0)
      if (!disposed) {
        notice.value = action === 'cancel' ? '邀請已取消，舊碼及工作階段已停用。' : '已重新派發，請使用下方的新 QR Code。'
        if (action === 'reissue') issued.value = result
      }
    } catch (failure) {
      if (!disposed) {
        // A lost response may follow a committed mutation. Refresh, never retry automatically.
        await load(0)
        error.value = `操作未能確認：${failure.message}。請先核對最新狀態再操作。`
      }
    } finally {
      if (!disposed) busy.value = false
    }
    return success
  }

  return {
    items, total, status, offset, loading, busy, error, issued, notice, limit, load, act,
    hasNext: computed(() => offset.value + limit < total.value),
    dispose() { disposed = true; requestVersion += 1 },
  }
}
