import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { t } from '../../i18n'
import { useSerialPoll } from '../../hooks/useSerialPoll'

const text = value => typeof value === 'string' && value.length > 0
const optionalText = value => value == null || typeof value === 'string'
const optionalNumber = value => value == null || (typeof value === 'number' && Number.isFinite(value) && value >= 0)
const jobStates = ['queued', 'running', 'completed', 'failed', 'interrupted']
const validJob = job => job && text(job.id) && ['backup', 'restore'].includes(job.action)
  && jobStates.includes(job.status) && text(job.created_at) && optionalText(job.message) && optionalText(job.checkpoint)
  && (job.report == null || (typeof job.report === 'object' && !Array.isArray(job.report)
    && optionalText(job.report.status) && optionalNumber(job.report.rto_seconds) && optionalNumber(job.report.rpo_seconds)))
const validHistory = data => Array.isArray(data?.archives) && data.archives.every(item => item && text(item.name)
  && Number.isSafeInteger(item.bytes) && item.bytes >= 0) && Array.isArray(data.jobs) && data.jobs.every(validJob)
const validPreview = (data, archive) => data?.name === archive && data.verified === true && data.compatible === true
  && typeof data.sha256 === 'string' && /^[a-f0-9]{64}$/.test(data.sha256)
  && optionalText(data.created_at) && data.security && typeof data.security === 'object' && !Array.isArray(data.security)
  && [data.security.encrypted, data.security.signed].every(value => value == null || typeof value === 'boolean')
  && data.metadata && typeof data.metadata === 'object' && !Array.isArray(data.metadata)
  && (data.metadata.application_schema_max == null || Number.isSafeInteger(data.metadata.application_schema_max))
  && Array.isArray(data.overwrites) && data.overwrites.every(text)
const emptyPreview = () => ({ data: null, loading: false, error: '' })
const hasRunning = data => data?.jobs.some(job => ['queued', 'running'].includes(job.status))

// A keyed view owns credentials, cached data and all in-flight request owners.
export function useSiteRecoveryData(token) {
  const [history, setHistory] = useState({ data: null, loading: true, error: '' })
  const [selected, setSelected] = useState('')
  const [preview, setPreview] = useState(emptyPreview)
  const [submission, setSubmission] = useState({ busy: false, error: '', notice: '', pendingId: '', uncertain: false })
  const read = useRef(history), selection = useRef(''), checked = useRef(null)
  const scope = useRef(null), previewOwner = useRef(null), submitOwner = useRef(null)
  const submitting = useRef(false), receipt = useRef(''), uncertain = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    scope.current = controller
    return () => { controller.abort(); previewOwner.current?.abort(); submitOwner.current?.abort() }
  }, [])
  const request = (path = '', options = {}) => api(`/admin/recovery/site${path}`, { ...options, headers: { 'X-Admin-Token': token } })
  function updateHistory(value) { read.current = value; setHistory(value) }
  function clearPreview() {
    previewOwner.current?.abort(); previewOwner.current = null; checked.current = null; setPreview(emptyPreview())
  }
  function chooseArchive(value) { clearPreview(); selection.current = value; setSelected(value) }
  const refresh = useSerialPoll(async ({ signal, current }) => {
    updateHistory({ ...read.current, loading: true, error: '' })
    try {
      const data = await request('', { signal })
      if (!validHistory(data)) throw new Error(t('整站恢复响应格式不正确，请重试。'))
      if (!current()) return
      const previous = read.current.data?.archives.find(item => item.name === selection.current)
      const archive = data.archives.find(item => item.name === selection.current)
      if (selection.current && (!archive || (previous && previous.bytes !== archive.bytes))) chooseArchive('')
      updateHistory({ data, loading: false, error: '' })
      uncertain.current = false
      setSubmission(old => ({ ...old, uncertain: false }))
      if (receipt.current && data.jobs.some(job => job.id === receipt.current)) {
        receipt.current = ''; setSubmission(old => ({ ...old, pendingId: '', uncertain: false }))
      }
    } catch (error) {
      if (!current()) return
      const denied = [401, 403].includes(error.status)
      if (denied) {
        chooseArchive(''); submitOwner.current?.abort()
        setSubmission({ busy: false, error: '', notice: '', pendingId: '', uncertain: false })
      }
      updateHistory({ data: denied ? null : read.current.data, loading: false, error: error.message || t('请求失败') })
    }
  }, { interval: 15000 })
  function ready() {
    return read.current.data && !read.current.loading && !read.current.error && !hasRunning(read.current.data)
      && !submitting.current && !receipt.current && !uncertain.current
  }
  async function verifyArchive() {
    if (!ready() || !selection.current) return
    clearPreview()
    const controller = new AbortController(), archive = selection.current, owner = scope.current
    previewOwner.current = controller
    const current = () => !owner.signal.aborted && !controller.signal.aborted && previewOwner.current === controller && archive === selection.current
    setPreview({ data: null, loading: true, error: '' })
    try {
      const data = await request('/preview', { method: 'POST', signal: controller.signal, body: JSON.stringify({ archive }) })
      if (!validPreview(data, archive)) throw new Error(t('整站恢复响应格式不正确，请重试。'))
      if (current()) { checked.current = data; setPreview({ data, loading: false, error: '' }) }
    } catch (error) {
      if (current()) setPreview({ data: null, loading: false, error: error.message || t('请求失败') })
    }
  }
  async function submit(action) {
    // A dialog opened earlier cannot bypass current history/archive checks.
    if (!ready() || preview.loading || !['backup', 'restore'].includes(action)
      || (action === 'restore' && (!checked.current || checked.current.name !== selection.current))) {
      throw new Error(t('请先刷新任务状态并完成当前归档校验。'))
    }
    submitting.current = true
    const controller = new AbortController(), owner = scope.current
    submitOwner.current = controller
    const current = () => !owner.signal.aborted && !controller.signal.aborted
    setSubmission({ busy: true, error: '', notice: '', pendingId: '', uncertain: false })
    try {
      const archive = selection.current
      const job = await request('/jobs', { method: 'POST', signal: controller.signal, body: JSON.stringify({ action,
        confirmation: action === 'restore' ? 'RESTORE SITE' : 'BACKUP SITE', archive, sha256: checked.current?.sha256 || '' }) })
      if (!validJob(job) || job.action !== action || (action === 'restore' && job.archive !== archive)) throw new Error(t('整站恢复响应格式不正确，请重试。'))
      if (!current()) return
      receipt.current = job.id
      clearPreview()
      setSubmission({ busy: false, error: '', pendingId: job.id, uncertain: false, notice: t('整站任务已接受：{0}。请以执行历史中的最终状态为准。', [job.id]) })
      // Accepted is not completed; a failed GET must not rewrite the receipt.
      void refresh()
    } catch (error) {
      if (current()) {
        uncertain.current = true
        setSubmission({ busy: false, notice: '', pendingId: '', uncertain: true, error: t('整站提交未确认：{0}。请先刷新任务历史核实，避免重复提交。', [error.message || t('请求失败')]) })
      }
      throw error
    } finally { submitting.current = false }
  }
  return { history: { ...history, refresh }, selected, chooseArchive, preview, verifyArchive, submission, submit,
    blocked: !history.data || history.loading || !!history.error || hasRunning(history.data) || submission.busy || !!submission.pendingId || submission.uncertain }
}
