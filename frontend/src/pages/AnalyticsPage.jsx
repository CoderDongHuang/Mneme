import { useEffect, useState } from 'react'
import { RefreshCw, Save, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import '../styles/centers.css'

const outcomes = { helpful: '有帮助', incorrect: '答案错误', low_confidence: '答案不确定', refusal: '拒答' }
const citations = { correct: '引用正确', incorrect: '引用错误', unclear: '无法确认', not_applicable: '无引用' }
const reasons = { none: '无', no_evidence: '资料不足', irrelevant_sources: '引用不相关', unsafe_content: '安全限制', other: '其他' }
const score = v => v == null ? '暂无样本' : Number(v).toFixed(1)
function Table({ rows = [], columns, label }) {
  return rows.length ? <div className="center-table"><table><caption>{label}</caption><thead><tr>{columns.map(([key, title]) => <th scope="col" key={key}>{title}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(([key]) => <td key={key}>{row[key] ?? '-'}</td>)}</tr>)}</tbody></table></div> : <p>暂无样本</p>
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ message_id: '', outcome: 'helpful', citation_rating: 'unclear', reason: 'none', note: '' })
  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    api(`/analytics?days=${days}`, { signal: controller.signal }).then(result => { setData(result); setError('') }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [days, refresh])
  async function save(event) {
    event.preventDefault(); setBusy(true); setNotice('')
    try { await api('/analytics/feedback', { method: 'PUT', body: JSON.stringify({ ...form, message_id: Number(form.message_id) }) }); setNotice('反馈已保存'); setError(''); setRefresh(v => v + 1) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function remove(id) {
    setBusy(true)
    try { await api(`/analytics/feedback/${id}`, { method: 'DELETE' }); setRefresh(v => v + 1); setNotice('反馈已删除'); setError('') } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const field = key => ({ value: form[key], onChange: e => setForm(v => ({ ...v, [key]: e.target.value })) })
  const quality = data?.trace_quality
  return <div className="center-page">
    <header className="center-head"><h1>学习分析</h1><button title="刷新学习分析" onClick={() => setRefresh(v => v + 1)}><RefreshCw size={18} /></button></header>
    <div className="center-toolbar"><label>时间窗口<select value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 30, 90].map(d => <option key={d} value={d}>{d} 天</option>)}</select></label></div>
    {error && <p role="alert" className="page-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!data && !error && <p role="status">加载中...</p>}
    {data && <>
      <section><h2>薄弱点趋势</h2><Table label="主题表现" rows={data.topics.map(row => ({ ...row, average_score: score(row.average_score), success_rate: `${(Number(row.success_rate) * 100).toFixed(1)}%`, early_score: score(row.early_score), recent_score: score(row.recent_score) }))} columns={[["topic", "主题"], ["observations", "样本数"], ["average_score", "平均分"], ["success_rate", "成功率"], ["early_score", "前半窗口"], ["recent_score", "后半窗口"]]} /></section>
      <section><h2>复习与测验</h2><Table label="每日学习记录" rows={data.daily.map(row => ({ ...row, event_type: row.event_type === 'review' ? '复习' : '测验', average_score: score(row.average_score) }))} columns={[["day", "日期"], ["event_type", "类型"], ["observations", "样本数"], ["average_score", "平均分"]]} /></section>
      <section><h2>检索运行信号</h2>{quality?.status === 'available' ? <dl><dt>Trace 样本</dt><dd>{quality.sampled_trace_rows}{quality.truncated ? '（最近 5000 行）' : ''} · 保留窗口 {quality.window_days} 天</dd><dt>意图分类低置信度</dt><dd>{quality.low_intent_confidence} / {quality.classified}</dd><dt>空检索</dt><dd>{quality.empty_retrievals} / {quality.retrievals}</dd><dt>执行错误</dt><dd>{quality.errors}</dd></dl> : <p>{quality?.status === 'unavailable' ? 'Trace 数据源不可用' : '暂无 Trace 样本'}</p>}</section>
      <section><h2>RAG 用户评价</h2><Table label="评价分布" rows={data.feedback_summary.map(row => ({ ...row, outcome: outcomes[row.outcome], citation_rating: citations[row.citation_rating], reason: reasons[row.reason] }))} columns={[["outcome", "回答评价"], ["citation_rating", "引用评价"], ["reason", "原因"], ["observations", "评价数"]]} /></section>
      <section><h2>回答反馈</h2><form onSubmit={save} className="center-feedback">
        <label>回答<select aria-label="回答" required {...field('message_id')}><option value="">选择回答</option>{data.answers.map(answer => <option key={answer.id} value={answer.id}>#{answer.id} · {answer.excerpt}</option>)}</select></label>
        <label>回答评价<select aria-label="回答评价" {...field('outcome')}>{Object.entries(outcomes).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
        <label>引用评价<select aria-label="引用评价" {...field('citation_rating')}>{Object.entries(citations).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
        <label>原因<select aria-label="原因" {...field('reason')}>{Object.entries(reasons).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>
        <label>备注<textarea rows={3} maxLength={1000} {...field('note')} /></label><button disabled={busy || !form.message_id}><Save size={18} />保存反馈</button>
      </form><ul className="center-list">{data.feedback.map(item => <li key={item.id}><div className="center-row"><span>回答 #{item.message_id} · {outcomes[item.outcome]} · {citations[item.citation_rating]} · {reasons[item.reason]}</span><button disabled={busy} title={`删除反馈 ${item.id}`} onClick={() => remove(item.id)}><Trash2 size={18} /></button></div><p>{item.note}</p></li>)}</ul></section>
    </>}
  </div>
}
