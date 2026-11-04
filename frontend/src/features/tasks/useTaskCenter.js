import { useCallback, useEffect, useRef, useState } from 'react'
import { endpoints, openNotificationStream } from '../../api/client'
import { useSerialPoll } from '../../hooks/useSerialPoll'
import { t } from '../../i18n'

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const text = value => value == null || typeof value === 'string'
const count = value => value == null || (Number.isSafeInteger(value) && value >= 0)
const token = value => typeof value === 'string' && /^[\w.-]{1,100}$/.test(value)

function validTasks(value) {
  return Array.isArray(value) && new Set(value.map(item => item?.task_id)).size === value.length
    && value.every(item => record(item) && token(item.task_id) && token(item.task_type) && token(item.status)
      && ['file_name', 'error_message', 'created_at', 'updated_at', 'next_attempt_at'].every(key => text(item[key]))
      && ['attempt_count', 'max_attempts'].every(key => count(item[key]))
      && (item.aggregate_id == null || count(item.aggregate_id))
      && (item.cleanup_report == null || typeof item.cleanup_report === 'string' || record(item.cleanup_report)))
}
function validLogs(value) {
  return Array.isArray(value) && value.every(item => record(item) && token(item.operation_id)
    && token(item.step) && token(item.status) && text(item.created_at) && text(item.error_message))
}

function useTaskRead(read, valid, failure) {
  const revision = useRef(0)
  const [state, setState] = useState({ data: null, loading: true, error: '' })
  const refresh = useSerialPoll(async ({ signal, current }) => {
    const version = revision.current
    // Retain a previous failure until a successful read; refreshing cannot make
    // stale data authoritative or temporarily re-enable mutation controls.
    setState(old => ({ ...old, loading: true }))
    try {
      const data = await read({ signal })
      if (!valid(data)) throw new Error('Invalid task center response')
      if (current() && version === revision.current) setState({ data, loading: false, error: '' })
    } catch {
      if (current() && version === revision.current) setState(old => ({ ...old, loading: false, error: t(failure) }))
    }
  })
  const invalidate = useCallback(() => {
    revision.current++
    setState(old => ({ ...old, loading: true }))
    void refresh()
  }, [refresh])
  return { ...state, refresh, invalidate }
}

export default function useTaskCenter() {
  const tasks = useTaskRead(endpoints.tasks, validTasks, '任务列表加载失败。已有记录可能不是最新状态，请重试。')
  const logs = useTaskRead(endpoints.operations, validLogs, '阶段记录加载失败。任务状态仍以列表为准，请重试。')
  const refreshTasks = tasks.refresh, refreshLogs = logs.refresh
  const refresh = useCallback(() => { void refreshTasks(); void refreshLogs() }, [refreshTasks, refreshLogs])
  useEffect(() => { const stream = openNotificationStream(refresh); return () => stream.close() }, [refresh])

  const scope = useRef(null)
  const lock = useRef(false)
  const [action, setAction] = useState({ busy: false, error: '', notice: '' })
  useEffect(() => {
    const controller = new AbortController()
    scope.current = controller
    return () => { controller.abort(); scope.current = null }
  }, [])
  async function act(task, kind) {
    const controller = scope.current
    if (lock.current || !controller || tasks.loading || tasks.error || !tasks.data) return
    const current = tasks.data.find(item => item.task_id === task.task_id)
    const allowed = kind === 'cancel'
      ? current?.task_type === 'document_ingest' && ['pending', 'retry', 'processing'].includes(current.status)
      : kind === 'retry' && ['failed', 'retry'].includes(current?.status)
    if (!allowed) return
    lock.current = true
    setAction({ busy: true, error: '', notice: '' })
    try {
      const send = kind === 'cancel' ? endpoints.cancelTask : endpoints.retryTask
      const receipt = await send(current.task_id, { signal: controller.signal })
      if (controller.signal.aborted || scope.current !== controller) return
      if (!record(receipt) || !token(receipt.task_id)
        || receipt.task_id !== current.task_id
        || !(kind === 'cancel' ? ['cancelling', 'cancelled'].includes(receipt.status) : receipt.status === 'retry')) {
        throw new Error(t('提交结果未确认，请刷新任务核实后再操作。'))
      }
      setAction({ busy: false, error: '', notice: t(kind === 'cancel'
        ? '取消请求已提交，最终结果以服务端状态为准' : '重试已提交，原失败记录保留在阶段日志中') })
      tasks.invalidate()
      void logs.refresh()
      return receipt.task_id
    } catch (error) {
      if (!controller.signal.aborted && scope.current === controller) {
        setAction({ busy: false, notice: '', error: typeof error.message === 'string' ? error.message : t('提交结果未确认，请刷新任务核实后再操作。') })
        // Never automatically resend a mutation whose outcome is unknown.
        tasks.invalidate()
      }
    } finally { lock.current = false }
  }
  return { tasks, logs, refresh, act, ...action }
}
