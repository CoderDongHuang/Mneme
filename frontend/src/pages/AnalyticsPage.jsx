import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { RefreshCw, Save, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { Link } from 'react-router-dom'
import '../styles/centers.css'

import { MetricCards } from '../components/ReferenceUI'
import { ActivityCalendar, DailyChart } from '../components/LearningCharts'

const outcomes = { helpful: '有帮助', incorrect: '答案错误', low_confidence: '答案不确定', refusal: '拒答' }
const citations = { correct: '引用正确', incorrect: '引用错误', unclear: '无法确认', not_applicable: '无引用' }
const reasons = { none: '无', no_evidence: '资料不足', irrelevant_sources: '引用不相关', unsafe_content: '安全限制', other: '其他' }
const score = v => v == null ? t("暂无样本") : Number(v).toFixed(1)
function Table({ rows = [], columns, label }) {
  useI18n();
  return rows.length ? <div className="center-table" tabIndex={0} role="region" aria-label={t(label)}><table className="analytics-table"><caption>{t(label)}</caption><thead><tr>{columns.map(([key, title]) => <th scope="col" key={key}>{title}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{columns.map(([key]) => <td key={key}>{row[key] ?? '-'}</td>)}</tr>)}</tbody></table></div> : <p>{t("暂无样本")}</p>
}

export default function AnalyticsPage() {
  useI18n();
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ message_id: '', outcome: 'helpful', citation_rating: 'unclear', reason: 'none', note: '' })
  useEffect(() => {
    const controller = new AbortController()
    api(`/analytics?days=${days}`, { signal: controller.signal }).then(result => { setData(result); setError('') }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [days, refresh])
  async function save(event) {
    event.preventDefault(); setBusy(true); setNotice('')
    try { await api('/analytics/feedback', { method: 'PUT', body: JSON.stringify({ ...form, message_id: Number(form.message_id) }) }); setNotice(t("反馈已保存")); setError(''); setRefresh(v => v + 1) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function remove(id) {
    setBusy(true)
    try { await api(`/analytics/feedback/${id}`, { method: 'DELETE' }); setRefresh(v => v + 1); setNotice(t("反馈已删除")); setError('') } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const field = key => ({ value: form[key], onChange: e => setForm(v => ({ ...v, [key]: e.target.value })) })
  function exportReport() {
    const report = { generated_at: new Date().toISOString(), window_days: days, definitions: t("学习指标来自实际测验与复习记录；主题平均分和成功率按窗口内观察计算。前后半窗口样本可能不同，不能推断因果。用户评价与检索信号单独统计，不代表掌握程度。"), data }
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `mneme-learning-${days}days.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const quality = data?.trace_quality
  return <div className="center-page reference-analytics">
    <header className="center-head"><h1>{t("学习分析")}</h1><button title={t("刷新学习分析")} aria-label={t("刷新学习分析")} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={18} /></button></header>
    <div className="center-toolbar"><label>{t("时间窗口")}<select aria-label={t("时间窗口")} value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 30, 90].map(d => <option key={d} value={d}>{d}{t(" 天")}</option>)}</select></label><button disabled={!data} onClick={exportReport}>{t("导出含统计口径的报告")}</button></div>
    {error && <p role="alert" className="page-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!data && !error && <p role="status">{t("加载中...")}</p>}
    {data && <>
      <p className="analysis-definition">{t('学习指标来自实际测验与复习记录。前后窗口样本不同，变化不代表因果。')}</p>
      <MetricCards items={[{label:t('学习记录'),value:data.daily.reduce((sum,row)=>sum+Number(row.observations||0),0)},{label:t('活跃天数'),value:new Set(data.daily.map(row=>String(row.day).slice(0,10))).size},{label:t('知识主题'),value:data.topics.length},{label:t('平均分'),value:(()=>{const n=data.topics.reduce((sum,row)=>sum+Number(row.observations||0),0);return n?(data.topics.reduce((sum,row)=>sum+Number(row.average_score||0)*Number(row.observations||0),0)/n).toFixed(1):'—'})()}]} />
      {data.topics.reduce((sum,row)=>sum+Number(row.observations||0),0)<4&&<p className="sample-note" role="status">{t('样本不足，暂不判断学习趋势。完成复习或测验后再查看。')}</p>}
      <div className="analysis-layout"><div className="analysis-main"><div className="analysis-charts"><section className="analysis-panel"><h3>{t('学习活动趋势')}</h3><DailyChart rows={data.daily} days={days}/></section><section className="analysis-panel"><h3>{t('学习得分趋势')}</h3><DailyChart rows={data.daily} days={days} line/></section></div>
      <div className="analysis-charts"><section className="analysis-panel"><h3>{t('知识点表现')}</h3>{data.topics.length?data.topics.map(row=><div className="topic-performance" key={row.topic}><span>{row.topic}</span><div className="confidence-bar"><span style={{width:`${Math.max(0,Math.min(100,Number(row.average_score||0)))}%`}}/></div><strong>{score(row.average_score)}</strong><small>{row.observations}{t(' 次观察')}</small></div>):<p className="muted">{t('暂无样本')}</p>}</section>
      <section className="analysis-panel"><h3>{t('需要加强的知识点')}</h3>{data.topics.some(row=>Number(row.success_rate)<.8)?data.topics.filter(row=>Number(row.success_rate)<.8).map(row=><div className="weak-topic" key={row.topic}><span>{row.topic}<small>{t('成功率 ')}{(Number(row.success_rate)*100).toFixed(1)}%</small></span><Link to={`/review?topic=${encodeURIComponent(row.topic)}`}>{t('开始复习')}</Link><Link to={`/memory?search=${encodeURIComponent(row.topic)}`}>{t('关联记忆')}</Link></div>):<p className="muted">{t('暂无可分析的薄弱知识点。')}</p>}<Link className="text-link" to="/quiz">{t('进入测验 →')}</Link></section></div>
      <details className="analysis-panel"><summary>{t('统计明细与计算口径')}</summary><p>{t('平均分按观察次数加权；日历仅展示所选统计窗口，未记录的日期不计入活跃天数。')}</p><Table label={t('主题表现')} rows={data.topics.map(row=>({...row,average_score:score(row.average_score),success_rate:`${(Number(row.success_rate)*100).toFixed(1)}%`,early_score:score(row.early_score),recent_score:score(row.recent_score)}))} columns={[["topic",t('主题')],["observations",t('样本数')],["average_score",t('平均分')],["success_rate",t('成功率')],["early_score",t('前半窗口')],["recent_score",t('后半窗口')]]}/><Table label={t('每日学习记录')} rows={data.daily.map(row=>({...row,event_type:row.event_type==='review'?t('复习'):t('测验'),average_score:score(row.average_score)}))} columns={[["day",t('日期')],["event_type",t('类型')],["observations",t('样本数')],["average_score",t('平均分')]]}/></details>
      </div><aside className="analysis-sidebar"><ActivityCalendar rows={data.daily}/><section className="analysis-panel"><h3>{t('最近学习记录')}</h3>{[...data.daily].sort((a,b)=>String(b.day).localeCompare(String(a.day))).slice(0,6).map((row,index)=><div className="upcoming-card" key={index}><strong>{row.event_type==='review'?t('复习'):t('测验')} · {row.observations}</strong><small>{String(row.day).slice(0,10)} · {t('平均分 ')}{score(row.average_score)}</small></div>)}{!data.daily.length&&<p className="muted">{t('完成复习或测验后，学习记录会显示在这里。')}</p>}</section></aside></div>
      <details className="analysis-panel analysis-diagnostics"><summary>{t('检索质量与回答反馈')}</summary>
      <section><h2>{t("检索运行信号")}</h2>{quality?.status === 'available' ? <dl><dt>{t("Trace 样本")}</dt><dd>{quality.sampled_trace_rows}{quality.truncated ? t("（最近 5000 行）") : ''}{t(" · 保留窗口 ")}{quality.window_days}{t(" 天")}</dd><dt>{t("意图分类低置信度")}</dt><dd>{quality.low_intent_confidence} / {quality.classified}</dd><dt>{t("空检索")}</dt><dd>{quality.empty_retrievals} / {quality.retrievals}</dd><dt>{t("执行错误")}</dt><dd>{quality.errors}</dd></dl> : <p>{quality?.status === 'unavailable' ? t("Trace 数据源不可用") : t("暂无 Trace 样本")}</p>}</section>
      <section><h2>{t("RAG 用户评价")}</h2><Table label={t("评价分布")} rows={data.feedback_summary.map(row => ({ ...row, outcome: t(outcomes[row.outcome]), citation_rating: t(citations[row.citation_rating]), reason: t(reasons[row.reason]) }))} columns={[["outcome", t("回答评价")], ["citation_rating", t("引用评价")], ["reason", t("原因")], ["observations", t("评价数")]]} /></section>
      <section><h2>{t("回答反馈")}</h2><form onSubmit={save} className="center-feedback">
        <label>{t("回答")}<select aria-label={t("回答")} required {...field('message_id')}><option value="">{t("选择回答")}</option>{data.answers.map(answer => <option key={answer.id} value={answer.id}>#{answer.id} · {answer.excerpt}</option>)}</select></label>
        <label>{t("回答评价")}<select aria-label={t("回答评价")} {...field('outcome')}>{Object.entries(outcomes).map(([key, title]) => <option key={key} value={key}>{t(title)}</option>)}</select></label>
        <label>{t("引用评价")}<select aria-label={t("引用评价")} {...field('citation_rating')}>{Object.entries(citations).map(([key, title]) => <option key={key} value={key}>{t(title)}</option>)}</select></label>
        <label>{t("原因")}<select aria-label={t("原因")} {...field('reason')}>{Object.entries(reasons).map(([key, title]) => <option key={key} value={key}>{t(title)}</option>)}</select></label>
        <label>{t("备注")}<textarea rows={3} maxLength={1000} {...field('note')} /></label><button disabled={busy || !form.message_id}><Save size={18} />{t("保存反馈")}</button>
      </form><ul className="center-list">{data.feedback.map(item => <li key={item.id}><div className="center-row"><span>{t("回答 #")}{item.message_id} · {t(outcomes[item.outcome])} · {t(citations[item.citation_rating])} · {t(reasons[item.reason])}</span><button disabled={busy} title={t("删除反馈 {0}", [item.id])} aria-label={t("删除反馈 {0}", [item.id])} onClick={() => remove(item.id)}><Trash2 size={18} /></button></div><p>{item.note}</p></li>)}</ul></section>
    </details></>}
  </div>
}
import '../styles/reference-pages.css'
