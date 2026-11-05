import { validBases } from '../../api/collectionValidation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { endpoints, openNotificationStream } from '../../api/client'
import { useSerialPoll } from '../../hooks/useSerialPoll'
import { t } from '../../i18n'

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const id = value => Number.isSafeInteger(value) && value > 0
const text = value => typeof value === 'string'
const optionalText = value => value == null || text(value)
const unique = (items, key) => new Set(items.map(item => item?.[key])).size === items.length
const validDocuments = value => Array.isArray(value) && unique(value, 'id') && value.every(item => record(item)
  && id(item.id) && text(item.fileName) && item.fileName.trim() && text(item.status) && item.status.trim()
  && ['errorMessage', 'updatedAt', 'parseReport'].every(key => optionalText(item[key]))
  && (item.chunkCount == null || (Number.isSafeInteger(item.chunkCount) && item.chunkCount >= 0)))
// Event history may legitimately contain multiple transitions of one task.
const validNotifications = value => Array.isArray(value) && value.every(item => record(item)
  && text(item.task_id) && item.task_id && text(item.status) && item.status
  && ['file_name', 'task_type', 'error_message'].every(key => optionalText(item[key])))
const initial = scope => ({ scope, data: null, loading: true, error: '' })

// A read failure never becomes an empty result. Polls are serial and a local
// receipt invalidates any older in-flight read before scheduling a fresh GET.
function useKnowledgeRead(read, valid, failure, { scope = '', enabled = true, interval } = {}) {
  const revision = useRef(0)
  const scopeRef = useRef(scope)
  useEffect(() => { scopeRef.current = scope }, [scope])
  const [state, setState] = useState(() => initial(scope))
  const refresh = useSerialPoll(async ({ signal, current }) => {
    const version = revision.current
    setState(old => old.scope === scope ? { ...old, loading: true } : initial(scope))
    try {
      const data = await read({ signal })
      if (!valid(data)) throw new Error('Invalid knowledge response')
      if (current() && version === revision.current) setState({ scope, data, loading: false, error: '' })
    } catch {
      if (current() && version === revision.current) setState(old => ({ ...old, loading: false, error: t(failure) }))
    }
  }, { interval, enabled, scope })
  const commit = useCallback(update => {
    if (scopeRef.current !== scope) return
    revision.current++
    setState(old => old.scope === scope ? { ...old, data: typeof update === 'function' ? update(old.data || []) : update } : old)
    void refresh()
  }, [refresh, scope])
  return { ...(state.scope === scope ? state : initial(scope)), refresh, commit }
}

export default function useKnowledgeReads() {
  const [activeKbId, setActiveKbId] = useState(null)
  const activeKbRef = useRef(null)
  const bases = useKnowledgeRead(endpoints.knowledgeBases, validBases,
    '资料库加载失败。已有记录可能不是最新状态，请重试。', { interval: 60000 })
  const documents = useKnowledgeRead(options => endpoints.documents(activeKbId, options), validDocuments,
    '文档列表加载失败。已有记录可能不是最新状态，请重试。', { scope: activeKbId, enabled: activeKbId !== null, interval: 2500 })
  const notifications = useKnowledgeRead(endpoints.notifications, validNotifications,
    '最近活动加载失败，请重试；文档状态仍以列表为准。', { interval: 10000 })
  const selectKb = useCallback(value => { activeKbRef.current = value; setActiveKbId(value) }, [])
  useEffect(() => {
    if (!bases.data) return
    const current = bases.data.find(item => item.id === activeKbRef.current)
    selectKb(current?.id ?? bases.data[0]?.id ?? null)
  }, [bases.data, selectKb])
  const refreshDocuments = documents.refresh, refreshNotifications = notifications.refresh
  useEffect(() => {
    const stream = openNotificationStream(() => { void refreshDocuments(); void refreshNotifications() })
    return () => stream.close()
  }, [refreshDocuments, refreshNotifications])
  return { bases, documents, notifications, activeKbId, activeKbRef, selectKb }
}
