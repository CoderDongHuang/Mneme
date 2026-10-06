import { RefreshCw, RotateCcw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { endpoints, openNotificationStream } from '../api/client'
import '../styles/centers.css'

const statuses = { pending: '等待领取', processing: '解析与向量化', retry: '等待重试', failed: '失败', completed: '完成', cancelled: '已取消' }
const types = { document_ingest: '文档解析', document_delete: '文档删除', knowledge_base_delete: '资料库删除' }
export default function TasksPage() {
  const [tasks, setTasks] = useState([])
  const [logs, setLogs] = useState([])
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  async function load() {
    try {
      const [items, events] = await Promise.all([endpoints.tasks(), endpoints.operations()])
      setTasks(items); setLogs(events); setLoaded(true); setError('')
    } catch (e) { setError(e.message) }
  }
  useEffect(() => {
    load()
    const stream = openNotificationStream(load)
    const timer = setInterval(load, 10000)
    return () => { stream.close(); clearInterval(timer) }
  }, [])
  async function act(task, action) {
    setBusy(true)
    try { await action(task.task_id); await load() } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <div className="center-page">
    <header className="center-head"><h1>任务中心</h1><button onClick={load} title="刷新" aria-label="刷新任务"><RefreshCw size={18} /></button></header>
    {error && <p role="alert" className="page-error">{error}</p>}
    <div className="center-toolbar"><label>状态<select aria-label="任务状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部</option>{Object.entries(statuses).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label><span role="status">{loaded ? `${tasks.length} 个任务` : '正在加载'}</span></div>
    <ul className="center-list">{tasks.filter(t => filter === 'all' || t.status === filter).map(t => <li key={t.task_id}>
      <div className="center-row"><strong>{t.file_name || types[t.task_type] || t.task_type}</strong><span>{t.status === 'processing' && t.task_type !== 'document_ingest' ? '执行中' : statuses[t.status] || t.status}</span></div>
      <p><small>{t.task_id} · {types[t.task_type]} · 尝试 {t.attempt_count}/{t.max_attempts}{t.next_attempt_at && ['pending', 'retry'].includes(t.status) ? ` · 下次执行 ${t.next_attempt_at}` : ''}</small></p>
      {t.error_message && <p className="page-error">{t.error_code}: {t.error_message}</p>}
      <div className="center-toolbar">
        {['failed', 'retry'].includes(t.status) && <button disabled={busy} onClick={() => act(t, endpoints.retryTask)}><RotateCcw size={16} />重试</button>}
        {t.task_type === 'document_ingest' && ['pending', 'retry'].includes(t.status) && <button disabled={busy} onClick={() => act(t, endpoints.cancelTask)}><X size={16} />取消等待任务</button>}
        <details><summary>阶段记录</summary><ol>{logs.filter(l => l.operation_id === t.task_id).reverse().map((l, i) => <li key={i}>{l.created_at} · {l.step} · {l.status}</li>)}</ol></details>
      </div>
    </li>)}</ul>
    {loaded && !tasks.some(t => filter === 'all' || t.status === filter) && <p>暂无符合条件的任务</p>}
  </div>
}
