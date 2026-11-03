import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'

const collections = {
  topics: ['topic', 'observations', 'average_score', 'success_rate', 'early_score', 'recent_score'],
  daily: ['day', 'event_type', 'observations', 'average_score'],
  feedback_summary: ['outcome', 'citation_rating', 'reason', 'observations'],
  feedback: ['id', 'message_id', 'outcome', 'citation_rating', 'reason', 'note'],
  answers: ['id', 'excerpt'],
}

function validate(result, days) {
  const scalar = value => value == null || typeof value === 'string' || typeof value === 'number' && Number.isFinite(value)
  if (!result || typeof result !== 'object' || Array.isArray(result)
    || result.window_days != null && result.window_days !== days
    || Object.entries(collections).some(([key, fields]) => !Array.isArray(result[key])
      || result[key].some(row => !row || typeof row !== 'object' || Array.isArray(row) || fields.some(field => !scalar(row[field]))))) {
    throw new Error('学习分析响应异常，请重试。')
  }
  return result
}

export default function useAnalyticsData(days) {
  const [revision, setRevision] = useState(0)
  const [read, setRead] = useState({ days: null, revision: -1, data: null, error: '' })
  const [write, setWrite] = useState({ busy: false, error: '', notice: '' })
  const alive = useRef(false)
  const writing = useRef(false)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    let current = true
    api(`/analytics?days=${days}`, { signal: controller.signal })
      .then(result => validate(result, days))
      .then(data => { if (current) setRead({ days, revision, data, error: '' }) })
      .catch(error => {
        if (current) setRead(old => ({ days, revision, data: old.days === days ? old.data : null, error: error.message || '学习分析加载失败，请重试。' }))
      })
    return () => { current = false; controller.abort() }
  }, [days, revision])

  // Bind visible data and exports to the window that actually produced them.
  // The revision changes synchronously, before the refresh effect starts.
  const settled = read.days === days && read.revision === revision
  const data = read.days === days ? read.data : null
  const error = settled ? read.error : ''
  const fresh = settled && !!data && !error
  async function mutate(path, options, notice) {
    if (writing.current || !fresh) return
    writing.current = true
    setWrite({ busy: true, error: '', notice: '' })
    try {
      await api(path, options)
      if (alive.current) {
        setWrite({ busy: false, error: '', notice })
        refresh()
      }
    } catch (error) {
      if (alive.current) setWrite({ busy: false, error: error.message || '反馈操作未确认，请刷新核实后重试。', notice: '' })
    } finally { writing.current = false }
  }
  return { data, error, loading: !settled, fresh, refresh, mutate, busy: write.busy, writeError: write.error, notice: write.notice }
}
