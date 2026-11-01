import { useState } from 'react'
import { api } from '../../api/client'
import { useSerialPoll } from '../../hooks/useSerialPoll'
import { t } from '../../i18n'

function useOperationsRead(path, token, valid) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })
  const refresh = useSerialPoll(async ({ signal, current }) => {
    setState(old => ({ ...old, loading: true, error: '' }))
    try {
      const data = await api(path, { signal, headers: { 'X-Admin-Token': token } })
      if (!valid(data)) throw new Error(t('运维响应格式不正确，请重试。'))
      if (current()) setState({ data, loading: false, error: '' })
    } catch (error) {
      if (current()) setState(old => ({ ...old, loading: false, error: error.message || t('请求失败') }))
    }
  }, { interval: 30000 })
  return { ...state, refresh }
}

const isSnapshot = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const isAudit = Array.isArray

// The credential-keyed content unmounts on lock/change. Each independent serial
// reader aborts and rejects late results; a slow snapshot never blocks audit.
export function useOperationsData(token) {
  const snapshot = useOperationsRead('/admin/operations', token, isSnapshot)
  const audit = useOperationsRead('/admin/audit', token, isAudit)
  return { snapshot, audit, refresh: () => { snapshot.refresh(); audit.refresh() } }
}
