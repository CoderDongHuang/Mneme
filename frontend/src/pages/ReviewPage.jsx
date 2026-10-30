import { t, useI18n } from '../i18n'
import { CalendarDays, Plus, RotateCcw, CheckCircle2, Clock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/client'
import { FeedbackBlock, Modal, PageHeader, StatusPill } from '../components/ui'
import { usePreferences } from '../state/PreferencesContext'

import { MetricCards, StudyCalendar } from '../components/ReferenceUI'

export default function ReviewPage() {
  useI18n();
  const { preferences } = usePreferences()
  const [cards, setCards] = useState([])
  const [plans, setPlans] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [flipped, setFlipped] = useState(false)
  const [selected, setSelected] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [form, setForm] = useState({ title: '', goal: '', target_date: '', prompt: '', answer: '' })
  async function load() {
    setError('')
    const results = await Promise.allSettled([endpoints.reviews(), endpoints.plans()])
    if (results[0].status === 'fulfilled') setCards(results[0].value || [])
    if (results[1].status === 'fulfilled') setPlans(results[1].value || [])
    setError(results.filter(result => result.status === 'rejected').map(result => result.reason.message).join(' · ')); setLoaded(true)
  }
  useEffect(() => { let active = true; Promise.allSettled([endpoints.reviews(), endpoints.plans()]).then(results => { if (active) { if (results[0].status === 'fulfilled') setCards(results[0].value || []); if (results[1].status === 'fulfilled') setPlans(results[1].value || []); setError(results.filter(r => r.status === 'rejected').map(r => r.reason.message).join(' · ')); setLoaded(true) } }).catch(e => { if (active) { setError(e.message); setLoaded(true) } }); return () => { active = false } }, [])
  const topic = new URLSearchParams(window.location.search).get('topic') || ''
  const due = cards.filter(card => new Date(card.due_at) <= new Date() && (!topic || `${card.prompt} ${card.answer}`.toLowerCase().includes(topic.toLowerCase())))
  const current = due.find(card => card.id === selected) || due[0]
  async function rate(rating) {
    if (!current || !flipped || lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const saved = await endpoints.reviewCard(current.id, rating)
      setCards(items => items.map(item => item.id === saved.id ? saved : item)); setFlipped(false); setSelected(null)
      setNotice(t("评分已保存，下次复习：{0}", [new Date(saved.due_at).toLocaleString(preferences.language, { timeZone: preferences.timezone })]))
    } catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  async function create(event) {
    event.preventDefault(); if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { await endpoints.createPlan({ title: form.title, goal: form.goal, target_date: form.target_date, cards: form.prompt.trim() ? [{ prompt: form.prompt, answer: form.answer }] : [] }); setOpen(false); setForm({ title: '', goal: '', target_date: '', prompt: '', answer: '' }); await load(); setNotice(t("计划已创建，复习卡使用你填写的真实答案")) }
    catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  return <div className="standard-page reference-page reference-review">
    <PageHeader eyebrow={t("循序渐进")} title={t("复习计划")} description={t("从今天的一张卡片开始，把理解留得更久。")}><button className="primary-button" onClick={() => setOpen(true)}><Plus size={17} />{t("制定计划")}</button></PageHeader>
    <FeedbackBlock error={error} message={notice} onRetry={error ? load : undefined} />
    <div className="study-layout"><div className="study-main"><MetricCards items={[{label:t('今日待复习'),value:due.length,icon:Clock},{label:t('已复习卡片'),value:cards.filter(card=>card.review_count>0).length,icon:CheckCircle2},{label:t('学习计划'),value:plans.length,icon:CalendarDays}]} /><section className="study-card" aria-live="polite">
      {!loaded ? <p role="status">{t("正在读取复习卡…")}</p> : current ? <><div className="action-row"><StatusPill>{current.origin === 'quiz_mistake' ? t("错题巩固") : t("学习卡片")}</StatusPill><span className="muted">{t("待复习 ")}{due.length}{t(" · 已复习 ")}{current.review_count || 0}{t(" 次")}</span></div><h2>{current.prompt}</h2><p className="muted">{t("先回忆，再翻面核对。评分决定下一次复习时间。")}</p>{flipped ? <div className="answer-panel"><h3>{t("参考答案")}</h3><p className="preserve-space">{current.answer}</p></div> : <button className="flip-button" onClick={() => setFlipped(true)}><RotateCcw size={18} />{t("查看答案")}</button>}{flipped && <div className="rating-actions" aria-label={t("复习评分")}>{[[0, t("忘记了")], [3, t("有些困难")], [4, t("基本掌握")], [5, t("很轻松")]].map(([rating, label]) => <button key={rating} disabled={busy} onClick={() => rate(rating)}>{t(label)}</button>)}</div>}{due.length > 1 && <button className="text-button" disabled={busy} onClick={() => { const index = due.findIndex(card => card.id === current.id); setSelected(due[(index + 1) % due.length].id); setFlipped(false) }}>{t("暂时跳过")}</button>}</> : <div className="empty-state"><CalendarDays size={32} /><h2>{t("今天的复习已就绪")}</h2><p>{t("当前没有到期卡片。你可以制定计划，或通过测验生成错题卡。")}</p><Link to="/quiz" className="text-link">{t("开始一次测验 →")}</Link></div>}
    </section></div><aside className="study-sidebar"><StudyCalendar cards={cards}/><section className="context-panel"><h3>{t('即将到来的复习')}</h3>{cards.filter(card=>new Date(card.due_at)>new Date()).sort((a,b)=>new Date(a.due_at)-new Date(b.due_at)).slice(0,5).map(card=><div className="upcoming-card" key={card.id}><strong>{card.prompt}</strong><small>{new Date(card.due_at).toLocaleString(preferences.language,{timeZone:preferences.timezone})}</small></div>)}{!cards.some(card=>new Date(card.due_at)>new Date())&&<p className="muted">{t('暂无记录')}</p>}</section><section className="context-panel"><h3>{t("我的计划")}</h3>{plans.length ? <ul className="plain-list">{plans.map(plan => <li key={plan.id}><strong>{plan.title}</strong><p>{plan.goal}</p><small className="muted">{plan.target_date || t("未设置截止日")}</small></li>)}</ul> : <p className="muted">{t("还没有计划。")}</p>}<h3>{t("复习方法")}</h3><p className="muted">{t("根据你的 0–5 评分、历史间隔和学习结果调整下次到期日。这里不估算学习时长，也不把评分视为掌握保证。")}</p></section></aside></div>
    <Modal open={open} title={t("制定学习计划")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={create}><FeedbackBlock error={error} /><label>{t("计划名称")}<input required maxLength={120} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label><label>{t("学习目标")}<textarea required value={form.goal} onChange={e => setForm({ ...form, goal: e.target.value })} /></label><label>{t("目标日期")}<input type="date" value={form.target_date} onChange={e => setForm({ ...form, target_date: e.target.value })} /></label><h3>{t("添加一张复习卡（可选）")}</h3><label>{t("问题")}<textarea maxLength={10000} value={form.prompt} onChange={e => setForm({ ...form, prompt: e.target.value })} /></label><label>{t("参考答案")}<textarea required={!!form.prompt.trim()} maxLength={10000} value={form.answer} onChange={e => setForm({ ...form, answer: e.target.value })} /></label><button className="primary-button" disabled={busy}>{busy ? t("创建中…") : t("创建计划")}</button></form></Modal>
  </div>
}
import '../styles/reference-pages.css'
