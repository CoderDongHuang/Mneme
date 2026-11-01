import { taskStatusLabels } from '../utils/statuses'
import { useFormatters } from '../hooks/useFormatters'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { RefreshCw, RotateCcw, X, Play, Clock, CheckCircle2, AlertCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints, openNotificationStream } from '../api/client'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import { useSerialPoll } from '../hooks/useSerialPoll'
import '../styles/centers.css'

import { DetailPane, MetricCards } from '../components/ReferenceUI'
import CleanupChecklist from '../components/CleanupChecklist'
import { taskDiagnostics, taskEvents, taskFailureMessage } from '../features/tasks/presentation'

const statuses = Object.fromEntries(['pending', 'processing', 'retry', 'cancelling', 'failed', 'completed', 'cancelled'].map(key => [key, taskStatusLabels[key]]))
const types = { document_ingest: '文档解析', document_index_repair: '词法索引修复', document_delete: '文档删除', knowledge_base_delete: '资料库删除', memory_candidates: '候选记忆保存' }
const terminal = ['failed', 'completed', 'cancelled']
export default function TasksPage() {
  const dates = useDateFormatter()
  const fmt = useFormatters()
  useI18n();
  const [tasks, setTasks] = useState([])
  const [logs, setLogs] = useState([])
  const [filter, setFilter] = useState('all')
  const [type, setType] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [logsLoaded, setLogsLoaded] = useState(false)
  const [taskError, setTaskError] = useState('')
  const [logsError, setLogsError] = useState('')
  const lock = useRef(false)
  const refresh = useSerialPoll(async ({ current }) => {
    const results = await Promise.allSettled([endpoints.tasks(), endpoints.operations()])
    if (!current()) return
    if (results[0].status === 'fulfilled') { setTasks(results[0].value || []); setLoaded(true) }
    if (results[1].status === 'fulfilled') { setLogs(results[1].value || []); setLogsLoaded(true) }
    setTaskError(results[0].status === 'rejected' ? t('任务列表加载失败。已有记录可能不是最新状态，请重试。') : '')
    setLogsError(results[1].status === 'rejected' ? t('阶段记录加载失败。任务状态仍以列表为准，请重试。') : '')
  })
  useEffect(() => { const stream = openNotificationStream(refresh); return () => stream.close() }, [refresh])
  async function act(task, action) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try { await action(task.task_id); setNotice(action === endpoints.cancelTask ? t("取消请求已提交，最终结果以服务端状态为准") : t("重试已提交，原失败记录保留在阶段日志中")); await refresh() }
    catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  const selected = tasks.find(t => t.task_id === selectedId)
  const events = taskEvents(logs, selectedId)
  const visible = tasks.filter(t => (filter === 'all' || t.status === filter) && (type === 'all' || t.task_type === type))
  return <div className="standard-page reference-page reference-tasks"><PageHeader eyebrow={t("后台工作，有迹可循")} title={t("任务中心")} description={t("查看真实执行阶段，诊断失败，并安全地重试或取消任务。")}><button onClick={refresh} aria-label={t("刷新任务")}><RefreshCw size={18} />{t("刷新")}</button></PageHeader>
    <FeedbackBlock error={[error, taskError, logsError].filter(Boolean).join(' · ')} message={notice} onRetry={error || taskError || logsError ? refresh : undefined} />
    <MetricCards items={[[t('运行中'),['processing','cancelling'],Play],[t('等待中'),['pending','retry'],Clock],[t('已完成'),['completed'],CheckCircle2],[t('失败'),['failed'],AlertCircle]].map(([label,values,icon])=>({label,value:loaded ? tasks.filter(task=>values.includes(task.status)).length : '—',icon}))} />
    <div className="reference-split task-split"><section>
    <div className="page-toolbar"><label>{t("状态")}<select aria-label={t("任务状态")} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("全部")}</option>{Object.entries(statuses).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><label>{t("类型")}<select value={type} onChange={e => setType(e.target.value)}><option value="all">{t("全部类型")}</option>{Object.entries(types).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><span role="status">{taskError ? t('任务状态暂不可刷新') : loaded ? t("{0} 个任务 · 最近最多 100 条", [fmt.integer(visible.length)]) : t("正在加载")}</span></div>
    <div className="reference-table-wrap" tabIndex={0} role="region" aria-label={t('任务列表')} aria-busy={!loaded && !taskError}><table className="reference-table"><thead><tr>{['任务','类型','执行阶段','开始时间','状态'].map(label=><th scope="col" key={label}>{t(label)}</th>)}</tr></thead><tbody>{visible.map(task=><tr key={task.task_id} className={selectedId===task.task_id?'is-selected':''}><td><button aria-pressed={selectedId===task.task_id} onClick={()=>setSelectedId(task.task_id)}>{task.file_name||t(types[task.task_type])||task.task_type}<small>{t('尝试 ')}{fmt.integer(task.attempt_count)}/{fmt.integer(task.max_attempts)}</small></button></td><td>{t(types[task.task_type])||task.task_type}</td><td>{taskEvents(logs, task.task_id)[0]?.step||fmt.status(task.status)}</td><td>{task.created_at?dates.dateTime(task.created_at):'—'}</td><td><StatusPill tone={task.status==='failed'?'danger':task.status==='completed'?'success':'neutral'}>{fmt.status(task.status)||task.status}</StatusPill></td></tr>)}</tbody></table></div>
    {loaded && !taskError && !visible.length && <div className="empty-state"><h2>{t("暂无符合条件的任务")}</h2><p>{t("上传或删除资料后，可以在这里跟踪执行过程。")}</p></div>}
    <section className="activity-timeline"><h3>{t('最近活动')}</h3><ol>{logs.slice(0,8).map((event,i)=><li key={i}><span className="timeline-dot"/><div><strong>{event.step} · {fmt.status(event.status)}</strong><small>{dates.dateTime(event.created_at)}</small>{event.error_message&&<p className="error-text">{t(taskFailureMessage(event.status, tasks.find(task => task.task_id === event.operation_id)?.task_type))}</p>}</div><button className="text-button" onClick={()=>setSelectedId(event.operation_id)}>{t('查看详情')}</button></li>)}</ol>{!logs.length&&<p className="muted">{logsError ? t('阶段记录暂不可用') : logsLoaded ? t('暂无记录') : t('正在加载')}</p>}</section>
    </section><DetailPane open={!!selectedId} title={t("任务详情")} busy={busy} onClose={() => setSelectedId(null)}>{selected ? <><FeedbackBlock error={[error, taskError, logsError].filter(Boolean).join(' · ')} message={notice} /><h3>{selected.file_name || t(types[selected.task_type])}</h3><StatusPill tone={selected.status === 'failed' ? 'danger' : 'neutral'}>{fmt.status(selected.status)}</StatusPill><p>{t("阶段：")}{events[0]?.step || fmt.status(selected.status)}。{!terminal.includes(selected.status) && t("当前服务未提供可靠百分比，按阶段展示。")}</p><dl><dt>{t("执行编号")}</dt><dd className="break-word">{selected.task_id}</dd><dt>{t("已尝试")}</dt><dd>{fmt.integer(selected.attempt_count)} / {fmt.integer(selected.max_attempts)}</dd><dt>{t(selected.task_type === 'memory_candidates' ? '来源回答' : selected.task_type === 'knowledge_base_delete' ? '关联资料库' : '关联文档')}</dt><dd>{selected.aggregate_id ?? t("无文档 / 资料库任务")}</dd></dl>
      {selected.cleanup_report && <section aria-label={t('清理核验')}><h3>{t('清理核验')}</h3><CleanupChecklist report={selected.cleanup_report} /></section>}
      {(selected.error_message || ['cancelling','retry'].includes(selected.status)) && <div className="hint-panel"><h3>{t("需要处理")}</h3><p>{t(taskFailureMessage(selected.status, selected.task_type))}</p><p className="muted">{t(selected.task_type === 'memory_candidates' ? '回答已保存。候选记忆保存失败不会更改回答状态，可在修复服务后重试此任务。' : "检查文件格式与服务状态；修复原因后重试。重试前的错误仍保留在下方阶段记录中。")}</p></div>}
      <div className="action-row">{['failed', 'retry'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.retryTask)}><RotateCcw size={16} />{t("重试任务")}</button>}{selected.task_type === 'document_ingest' && ['pending', 'retry', 'processing'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.cancelTask)}><X size={16} />{t("请求取消")}</button>}<button disabled={!logsLoaded || !!taskError || !!logsError} onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify(taskDiagnostics(selected, events), null, 2)); setNotice(t("诊断信息已复制")) } catch { setError(t("无法访问剪贴板，请从详情中手动复制")) } }}>{t("复制诊断信息")}</button></div>
      <p className="muted">{t('诊断副本仅包含执行编号、类型、状态、次数、时间与阶段，不包含文件名、原始错误或内部路径。')}</p>
      <details><summary>{t("错误详情与阶段记录")}</summary><ol className="task-timeline">{events.slice().reverse().map((event, i) => <li key={i}><strong>{event.step} · {fmt.status(event.status)}</strong><time>{dates.dateTime(event.created_at)}</time>{event.error_message && <p>{t(taskFailureMessage(event.status, selected.task_type))}</p>}</li>)}</ol>{!events.length && <p>{logsError ? t('阶段记录暂不可用') : logsLoaded ? t("暂无可用的阶段日志。") : t('正在加载')}</p>}</details>
    </> : <p>{t("当前任务不在最近列表中，请刷新或查询审计记录。")}</p>}</DetailPane></div>
  </div>
}
import '../styles/reference-pages.css'
