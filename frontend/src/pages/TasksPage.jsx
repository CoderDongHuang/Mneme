import { t, useI18n } from '../i18n'
import { RefreshCw, RotateCcw, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints, openNotificationStream } from '../api/client'
import { FeedbackBlock, PageHeader, SideDrawer, StatusPill } from '../components/ui'
import { useSerialPoll } from '../hooks/useSerialPoll'
import '../styles/centers.css'

const statuses = { pending: '等待领取', processing: '执行中', retry: '等待重试', cancelling: '已请求取消', failed: '失败', completed: '完成', cancelled: '取消已完成' }
const types = { document_ingest: '文档解析', document_delete: '文档删除', knowledge_base_delete: '资料库删除' }
const terminal = ['failed', 'completed', 'cancelled']
export default function TasksPage() {
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
  const lock = useRef(false)
  const refresh = useSerialPoll(async ({ current }) => {
    const results = await Promise.allSettled([endpoints.tasks(), endpoints.operations()])
    if (!current()) return
    if (results[0].status === 'fulfilled') { setTasks(results[0].value || []); setLoaded(true) }
    if (results[1].status === 'fulfilled') setLogs(results[1].value || [])
    setError(results.filter(r => r.status === 'rejected').map(r => r.reason.message).join(' · '))
  })
  useEffect(() => { const stream = openNotificationStream(refresh); return () => stream.close() }, [refresh])
  async function act(task, action) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try { await action(task.task_id); setNotice(action === endpoints.cancelTask ? t("取消请求已提交，最终结果以服务端状态为准") : t("重试已提交，原失败记录保留在阶段日志中")); await refresh() }
    catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  const selected = tasks.find(t => t.task_id === selectedId)
  const events = logs.filter(l => l.operation_id === selectedId).slice().reverse()
  const visible = tasks.filter(t => (filter === 'all' || t.status === filter) && (type === 'all' || t.task_type === type))
  return <div className="standard-page"><PageHeader eyebrow={t("后台工作，有迹可循")} title={t("任务中心")} description={t("查看真实执行阶段，诊断失败，并安全地重试或取消任务。")}><button onClick={refresh} aria-label={t("刷新任务")}><RefreshCw size={18} />{t("刷新")}</button></PageHeader>
    <FeedbackBlock error={error} message={notice} onRetry={error ? refresh : undefined} />
    <div className="metric-strip">{[[t("运行中"), ['processing', 'cancelling']], [t("等待中"), ['pending', 'retry']], [t("已完成"), ['completed']], [t("失败"), ['failed']]].map(([label, values]) => <div key={t(label)}><span>{t(label)}</span><strong>{tasks.filter(t => values.includes(t.status)).length}</strong></div>)}</div>
    <div className="page-toolbar"><label>{t("状态")}<select aria-label={t("任务状态")} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("全部")}</option>{Object.entries(statuses).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><label>{t("类型")}<select value={type} onChange={e => setType(e.target.value)}><option value="all">{t("全部类型")}</option>{Object.entries(types).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><span role="status">{loaded ? t("{0} 个任务 · 最近最多 200 条", [visible.length]) : t("正在加载")}</span></div>
    <ul className="record-list">{visible.map(task => <li key={task.task_id}><button className="record-open" onClick={() => setSelectedId(task.task_id)}><span className="action-row"><strong>{task.file_name || t(types[task.task_type]) || task.task_type}</strong><StatusPill tone={task.status === 'failed' ? 'danger' : task.status === 'completed' ? 'success' : 'neutral'}>{t(statuses[task.status]) || task.status}</StatusPill></span><p>{t(types[task.task_type])}{t(" · 尝试 ")}{task.attempt_count}/{task.max_attempts}</p><small>{task.task_id}{task.next_attempt_at && ['pending', 'retry'].includes(task.status) ? t(" · 下次执行 {0}", [task.next_attempt_at]) : ''}</small>{task.error_message && <p className="error-text">{t("执行失败，请打开详情查看原因与恢复方法。")}</p>}</button></li>)}</ul>
    {loaded && !visible.length && <div className="empty-state"><h2>{t("暂无符合条件的任务")}</h2><p>{t("上传或删除资料后，可以在这里跟踪执行过程。")}</p></div>}
    <SideDrawer open={!!selectedId} title={t("任务详情")} busy={busy} onClose={() => setSelectedId(null)}>{selected ? <><FeedbackBlock error={error} message={notice} /><h3>{selected.file_name || t(types[selected.task_type])}</h3><StatusPill tone={selected.status === 'failed' ? 'danger' : 'neutral'}>{t(statuses[selected.status])}</StatusPill><p>{t("阶段：")}{events.at(-1)?.step || t(statuses[selected.status])}。{!terminal.includes(selected.status) && t("当前服务未提供可靠百分比，按阶段展示。")}</p><dl><dt>{t("执行编号")}</dt><dd className="break-word">{selected.task_id}</dd><dt>{t("已尝试")}</dt><dd>{selected.attempt_count} / {selected.max_attempts}</dd><dt>{t("关联文档")}</dt><dd>{selected.document_id || t("无文档 / 资料库任务")}</dd></dl>
      {selected.error_message && <div className="hint-panel"><h3>{t("需要处理")}</h3><p>{selected.error_message}</p><p className="muted">{t("检查文件格式与服务状态；修复原因后重试。重试前的错误仍保留在下方阶段记录中。")}</p></div>}
      <div className="action-row">{['failed', 'retry'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.retryTask)}><RotateCcw size={16} />{t("重试任务")}</button>}{selected.task_type === 'document_ingest' && ['pending', 'retry', 'processing'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.cancelTask)}><X size={16} />{t("请求取消")}</button>}<button onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify({ task: selected, stages: events }, null, 2)); setNotice(t("诊断信息已复制")) } catch { setError(t("无法访问剪贴板，请从详情中手动复制")) } }}>{t("复制诊断信息")}</button></div>
      <details><summary>{t("错误详情与阶段记录")}</summary>{selected.error_code && <code>{selected.error_code}</code>}<ol className="task-timeline">{events.map((event, i) => <li key={i}><strong>{event.step} · {event.status}</strong><time>{event.created_at}</time>{event.error_message && <p>{event.error_message}</p>}</li>)}</ol>{!events.length && <p>{t("暂无可用的阶段日志。")}</p>}</details>
    </> : <p>{t("当前任务不在最近列表中，请刷新或查询审计记录。")}</p>}</SideDrawer>
  </div>
}
