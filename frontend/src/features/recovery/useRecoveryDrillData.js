import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { t } from '../../i18n'
import { useSerialPoll } from '../../hooks/useSerialPoll'

const hasId = value => value && Number.isSafeInteger(value.id) && value.id > 0
const optionalText = value => value == null || typeof value === 'string'
const validRun = value => hasId(value) && Number.isSafeInteger(value.run_number)
  && optionalText(value.created_at) && optionalText(value.status) && optionalText(value.conclusion) && optionalText(value.html_url)
const validRuns = value => Array.isArray(value?.runs) && value.runs.every(validRun)
const validEvidence = (value, id) => validRun(value?.run) && value.run.id === id
  && Array.isArray(value.jobs) && value.jobs.every(job => hasId(job) && typeof job.name === 'string'
    && Array.isArray(job.steps) && job.steps.every(step => step && Number.isSafeInteger(step.number)
      && typeof step.name === 'string' && optionalText(step.status) && optionalText(step.conclusion)))
  && Array.isArray(value.artifacts) && value.artifacts.every(item => hasId(item) && typeof item.name === 'string'
    && Number.isSafeInteger(item.size_in_bytes) && item.size_in_bytes >= 0 && typeof item.expired === 'boolean')

// Mounted under a credential key: locking destroys all data and request owners.
export function useRecoveryDrillData(token) {
  const [history, setHistory] = useState({ data: null, loading: true, error: '' })
  const [detail, setDetail] = useState({ id: null, data: null, loading: false, error: '' })
  const [submission, setSubmission] = useState({ busy: false, error: '', notice: '' })
  const owner = useRef(null)
  const detailOwner = useRef(null)
  const submitting = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    owner.current = controller
    return () => { controller.abort(); detailOwner.current?.abort() }
  }, [])
  const refresh = useSerialPoll(async ({ signal, current }) => {
    setHistory(old => ({ ...old, loading: true, error: '' }))
    try {
      const data = await api('/admin/recovery', { signal, headers: { 'X-Admin-Token': token } })
      if (!validRuns(data)) throw new Error(t('恢复演练响应格式不正确，请重试。'))
      if (current()) setHistory({ data: data.runs, loading: false, error: '' })
    } catch (error) {
      if (current()) {
        const denied = [401, 403].includes(error.status)
        setHistory(old => ({ data: denied ? null : old.data, loading: false, error: error.message || t('请求失败') }))
        if (denied) {
          detailOwner.current?.abort()
          setDetail({ id: null, data: null, loading: false, error: '' })
        }
      }
    }
  }, { interval: 15000 })

  async function loadEvidence(id) {
    detailOwner.current?.abort()
    const controller = new AbortController()
    detailOwner.current = controller
    const current = () => !owner.current.signal.aborted && !controller.signal.aborted && detailOwner.current === controller
    setDetail({ id, data: null, loading: true, error: '' })
    try {
      const data = await api(`/admin/recovery/${id}`, { signal: controller.signal, headers: { 'X-Admin-Token': token } })
      if (!validEvidence(data, id)) throw new Error(t('恢复演练响应格式不正确，请重试。'))
      if (current()) setDetail({ id, data, loading: false, error: '' })
    } catch (error) {
      if (current()) setDetail({ id, data: null, loading: false, error: error.message || t('请求失败') })
    }
  }

  async function dispatch(confirmation) {
    if (submitting.current || confirmation !== 'ISOLATED DRILL') return false
    submitting.current = true
    const controller = owner.current
    setSubmission({ busy: true, error: '', notice: '' })
    try {
      const result = await api('/admin/recovery', { method: 'POST', signal: controller.signal, headers: { 'X-Admin-Token': token }, body: JSON.stringify({ confirmation }) })
      if (result?.status !== 'accepted') throw new Error(t('恢复演练响应格式不正确，请重试。'))
      if (controller.signal.aborted) return false
      setSubmission({ busy: false, error: '', notice: t('已提交隔离演练，请等待 GitHub 分配运行编号') })
      // A read failure must never turn an accepted dispatch into a failed POST.
      void refresh()
      return true
    } catch (error) {
      if (!controller.signal.aborted) setSubmission({ busy: false, error: t('演练提交未确认：{0}。请先刷新历史核实，避免重复提交。', [error.message || t('请求失败')]), notice: '' })
      return false
    } finally { submitting.current = false }
  }
  return { history: { ...history, refresh }, detail: { ...detail, refresh: () => loadEvidence(detail.id) }, submission, loadEvidence, dispatch }
}
