import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { RefreshCw, RotateCcw, X, Play, Clock, CheckCircle2, AlertCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints, openNotificationStream } from '../api/client'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import { useSerialPoll } from '../hooks/useSerialPoll'
import '../styles/centers.css'

import { DetailPane, MetricCards } from '../components/ReferenceUI'

const statuses = { pending: '等待领取', processing: '执行中', retry: '等待重试', cancelling: '已请求取消', failed: '失败', completed: '完成', cancelled: '取消已完成' }
const types = { document_ingest: '文档解析', document_index_repair: '词法索引修复', document_delete: '文档删除', knowledge_base_delete: '资料库删除' }
const terminal = ['failed', 'completed', 'cancelled']
export default function TasksPage() {
  const dates = useDateFormatter()
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
  return <div className="standard-page reference-page reference-tasks"><PageHeader eyebrow={t("后台工作，有迹可循")} title={t("任务中心")} description={t("查看真实执行阶段，诊断失败，并安全地重试或取消任务。")}><button onClick={refresh} aria-label={t("刷新任务")}><RefreshCw size={18} />{t("刷新")}</button></PageHeader>
    <FeedbackBlock error={error} message={notice} onRetry={error ? refresh : undefined} />
    <MetricCards items={[[t('运行中'),['processing','cancelling'],Play],[t('等待中'),['pending','retry'],Clock],[t('已完成'),['completed'],CheckCircle2],[t('失败'),['failed'],AlertCircle]].map(([label,values,icon])=>({label,value:tasks.filter(task=>values.includes(task.status)).length,icon}))} />
    <div className="reference-split task-split"><section>
    <div className="page-toolbar"><label>{t("状态")}<select aria-label={t("任务状态")} value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("全部")}</option>{Object.entries(statuses).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><label>{t("类型")}<select value={type} onChange={e => setType(e.target.value)}><option value="all">{t("全部类型")}</option>{Object.entries(types).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><span role="status">{loaded ? t("{0} 个任务 · 最近最多 200 条", [visible.length]) : t("正在加载")}</span></div>
    <div className="reference-table-wrap" tabIndex={0} role="region" aria-label={t('任务列表')}><table className="reference-table"><thead><tr>{['任务','类型','执行阶段','开始时间','状态'].map(label=><th scope="col" key={label}>{t(label)}</th>)}</tr></thead><tbody>{visible.map(task=><tr key={task.task_id} className={selectedId===task.task_id?'is-selected':''}><td><button onClick={()=>setSelectedId(task.task_id)}>{task.file_name||t(types[task.task_type])||task.task_type}<small>{t('尝试 ')}{task.attempt_count}/{task.max_attempts}</small></button></td><td>{t(types[task.task_type])||task.task_type}</td><td>{logs.filter(event=>event.operation_id===task.task_id).at(-1)?.step||t(statuses[task.status])}</td><td>{task.created_at?dates.dateTime(task.created_at):'—'}</td><td><StatusPill tone={task.status==='failed'?'danger':task.status==='completed'?'success':'neutral'}>{t(statuses[task.status])||task.status}</StatusPill></td></tr>)}</tbody></table></div>
    {loaded && !visible.length && <div className="empty-state"><h2>{t("暂无符合条件的任务")}</h2><p>{t("上传或删除资料后，可以在这里跟踪执行过程。")}</p></div>}
    <section className="activity-timeline"><h3>{t('最近活动')}</h3><ol>{logs.slice(-8).reverse().map((event,i)=><li key={i}><span className="timeline-dot"/><div><strong>{event.step} · {event.status}</strong><small>{dates.dateTime(event.created_at)}</small>{event.error_message&&<p className="error-text">{event.error_message}</p>}</div><button className="text-button" onClick={()=>setSelectedId(event.operation_id)}>{t('查看详情')}</button></li>)}</ol>{!logs.length&&<p className="muted">{t('暂无记录')}</p>}</section>
    </section><DetailPane open={!!selectedId} title={t("任务详情")} busy={busy} onClose={() => setSelectedId(null)}>{selected ? <><FeedbackBlock error={error} message={notice} /><h3>{selected.file_name || t(types[selected.task_type])}</h3><StatusPill tone={selected.status === 'failed' ? 'danger' : 'neutral'}>{t(statuses[selected.status])}</StatusPill><p>{t("阶段：")}{events.at(-1)?.step || t(statuses[selected.status])}。{!terminal.includes(selected.status) && t("当前服务未提供可靠百分比，按阶段展示。")}</p><dl><dt>{t("执行编号")}</dt><dd className="break-word">{selected.task_id}</dd><dt>{t("已尝试")}</dt><dd>{selected.attempt_count} / {selected.max_attempts}</dd><dt>{t("关联文档")}</dt><dd>{selected.document_id || t("无文档 / 资料库任务")}</dd></dl>
      {selected.error_message && <div className="hint-panel"><h3>{t("需要处理")}</h3><p>{selected.error_message}</p><p className="muted">{t("检查文件格式与服务状态；修复原因后重试。重试前的错误仍保留在下方阶段记录中。")}</p></div>}
      <div className="action-row">{['failed', 'retry'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.retryTask)}><RotateCcw size={16} />{t("重试任务")}</button>}{selected.task_type === 'document_ingest' && ['pending', 'retry', 'processing'].includes(selected.status) && <button disabled={busy} onClick={() => act(selected, endpoints.cancelTask)}><X size={16} />{t("请求取消")}</button>}<button onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify({ task: selected, stages: events }, null, 2)); setNotice(t("诊断信息已复制")) } catch { setError(t("无法访问剪贴板，请从详情中手动复制")) } }}>{t("复制诊断信息")}</button></div>
      <details><summary>{t("错误详情与阶段记录")}</summary>{selected.error_code && <code>{selected.error_code}</code>}<ol className="task-timeline">{events.map((event, i) => <li key={i}><strong>{event.step} · {event.status}</strong><time>{dates.dateTime(event.created_at)}</time>{event.error_message && <p>{event.error_message}</p>}</li>)}</ol>{!events.length && <p>{t("暂无可用的阶段日志。")}</p>}</details>
    </> : <p>{t("当前任务不在最近列表中，请刷新或查询审计记录。")}</p>}</DetailPane></div>
  </div>
}
import '../styles/reference-pages.css'
