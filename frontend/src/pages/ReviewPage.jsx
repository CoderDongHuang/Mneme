import { parseInstant } from '../utils/dates'
import { useFormatters } from '../hooks/useFormatters'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { CalendarDays, Plus, RotateCcw, CheckCircle2, Clock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/client'
import { FeedbackBlock, Modal, PageHeader, StatusPill } from '../components/ui'

import { MetricCards, StudyCalendar } from '../components/ReferenceUI'
import LoadingState from '../components/LoadingState'
import useReviewData from '../features/review/useReviewData'
import { validPlan, validRatingReceipt } from '../features/review/reviewValidation'
import { useAuth } from '../state/AuthContext'
import '../styles/reference-pages.css'

export default function ReviewPage() {
  const session = useAuth()?.session
  return <ReviewView key={session?.userId || session?.username || 'anonymous'} />
}

function ReviewView() {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n();
  const { cards: cardRead, plans: planRead } = useReviewData()
  const cards = cardRead.data || []
  const plans = planRead.data || []
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [flippedId, setFlippedId] = useState(null)
  const [selected, setSelected] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(null)
  const unavailable = cardRead.data === null || cardRead.loading || cardRead.error
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    // Cards can become due while this page is open (including database
    // rounding of a newly created card to the following second).
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const lock = useRef(false)
  const alive = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [form, setForm] = useState({ title: '', goal: '', target_date: '', prompt: '', answer: '' })
  const topic = new URLSearchParams(window.location.search).get('topic') || ''
  const due = cards.filter(card => (parseInstant(card.due_at)?.getTime() ?? NaN) <= now && (!topic || `${card.prompt} ${card.answer}`.toLowerCase().includes(topic.toLowerCase())))
  const current = due.find(card => card.id === selected) || due[0]
  const flipped = current && flippedId === current.id
  async function rate(rating) {
    if (!current || !flipped || lock.current || pending || unavailable) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    cardRead.invalidate()
    try {
      const saved = await endpoints.reviewCard(current.id, rating)
      if (!validRatingReceipt(saved, current, rating)) throw new Error('Invalid rating receipt')
      if (alive.current) {
        cardRead.commit(items => items.map(item => item.id === saved.id ? saved : item)); setFlippedId(null); setSelected(null)
        setNotice(t("评分已保存，下次复习：{0}", [dates.dateTime(saved.due_at)]))
      }
    } catch { if (alive.current) { setPending({ type: 'rating', checked: false }); setError(t('评分结果尚未确认，请先核对最新复习状态。')) } } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  async function create(event) {
    event.preventDefault(); if (lock.current || pending) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    cardRead.invalidate(); planRead.invalidate()
    try {
      const saved = await endpoints.createPlan({ title: form.title, goal: form.goal, target_date: form.target_date, cards: form.prompt.trim() ? [{ prompt: form.prompt, answer: form.answer }] : [] })
      if (!validPlan(saved) || saved.title !== form.title.trim() || saved.goal !== form.goal.trim() || (saved.target_date ?? '') !== form.target_date) throw new Error('Invalid plan receipt')
      if (alive.current) {
        setOpen(false); setForm({ title: '', goal: '', target_date: '', prompt: '', answer: '' })
        setNotice(t("计划已创建，复习卡使用你填写的真实答案"))
        void cardRead.refresh(); void planRead.refresh()
      }
    } catch { if (alive.current) { setPending({ type: 'plan', checked: false }); setError(t('计划创建结果尚未确认，请先核对已保存计划。')) } } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  async function checkReceipt() {
    if (lock.current || !pending) return
    lock.current = true; setBusy(true)
    try {
      const results = await Promise.all(pending.type === 'plan' ? [cardRead.refresh(), planRead.refresh()] : [cardRead.refresh()])
      if (alive.current) setPending(old => old && ({ ...old, checked: results.every(value => value !== undefined) }))
    } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  const receiptCheck = pending && <div className="form-stack" role="region" aria-label={t('提交结果核对')}>
    <p className="muted">{t('读取不会重新提交。请核对最新安排；刷新或离开页面不能撤销已提交操作，再次提交可能重复写入。')}</p>
    <button type="button" className="secondary-button" disabled={busy} onClick={checkReceipt}>{t(pending.type === 'plan' ? '核对已保存计划' : '核对最新复习状态')}</button>
    {(cardRead.error || (pending.type === 'plan' && planRead.error)) && <p role="alert">{t('核对读取失败，请重试核对；尚未重新提交。')}</p>}
    {pending.checked && <>
      {pending.type === 'plan' ? <ul className="plain-list">{plans.map(plan => <li key={plan.id}><strong>{plan.title}</strong><p>{plan.goal}</p></li>)}</ul> : <p>{t('已读取最新复习状态，请核对卡片及下次复习安排。')}</p>}
      <button type="button" className="secondary-button" disabled={busy || unavailable || (pending.type === 'plan' && (planRead.loading || planRead.error))} onClick={() => { setPending(null); setError('') }}>{t('已核实，继续操作')}</button>
    </>}
  </div>
  return <div className="standard-page reference-page reference-review">
    <PageHeader eyebrow={t("循序渐进")} title={t("复习计划")} description={t("从今天的一张卡片开始，把理解留得更久。")}><button className="primary-button" disabled={busy || !!pending} onClick={() => { setError(''); setOpen(true) }}><Plus size={17} />{t("制定计划")}</button></PageHeader>
    <FeedbackBlock error={open ? '' : error} message={notice} />
    {!open && receiptCheck}
    <div className="study-layout"><div className="study-main"><MetricCards items={[{label:t('今日待复习'),value:cardRead.data === null ? '—' : due.length,icon:Clock},{label:t('已复习卡片'),value:cardRead.data === null ? '—' : cards.filter(card=>card.review_count>0).length,icon:CheckCircle2},{label:t('学习计划'),value:planRead.data === null ? '—' : plans.length,icon:CalendarDays}]} /><section className="study-card" aria-label={t('复习卡片')} aria-busy={cardRead.loading} aria-live="polite">
      <button className="text-button" disabled={busy || cardRead.loading} onClick={cardRead.refresh}>{t('刷新复习卡')}</button>
      {cardRead.loading && <LoadingState label={t('正在读取复习卡…')} />}
      <FeedbackBlock error={cardRead.error ? t('复习卡加载失败，请重试。') : ''} onRetry={!busy ? cardRead.refresh : undefined} />
      {cardRead.error && cardRead.data !== null && <p>{t('已有复习卡可能不是最新状态。')}</p>}
      {current ? <><div className="action-row"><StatusPill>{current.origin === 'quiz_mistake' ? t("错题巩固") : t("学习卡片")}</StatusPill><span className="muted">{t("待复习 ")}{fmt.integer(due.length)}{t(" · 已复习 ")}{fmt.integer(current.review_count ?? 0)}{t(" 次")}</span></div><h2>{current.prompt}</h2><p className="muted">{t("先回忆，再翻面核对。评分决定下一次复习时间。")}</p>{flipped ? <div className="answer-panel"><h3>{t("参考答案")}</h3><p className="preserve-space">{current.answer}</p></div> : <button className="flip-button" onClick={() => setFlippedId(current.id)}><RotateCcw size={18} />{t("查看答案")}</button>}{flipped && <div className="rating-actions" aria-label={t("复习评分")}>{[[0, t("忘记了")], [3, t("有些困难")], [4, t("基本掌握")], [5, t("很轻松")]].map(([rating, label]) => <button key={rating} disabled={busy || !!pending || unavailable} onClick={() => rate(rating)}>{t(label)}</button>)}</div>}{due.length > 1 && <button className="text-button" disabled={busy} onClick={() => { const index = due.findIndex(card => card.id === current.id); setSelected(due[(index + 1) % due.length].id); setFlippedId(null) }}>{t("暂时跳过")}</button>}</> : cardRead.data !== null && !cardRead.loading && !cardRead.error && <div className="empty-state"><CalendarDays size={32} /><h2>{t("今天的复习已就绪")}</h2><p>{t("当前没有到期卡片。你可以制定计划，或通过测验生成错题卡。")}</p><Link to="/quiz" className="text-link">{t("开始一次测验 →")}</Link></div>}
    </section></div><aside className="study-sidebar">{cardRead.data !== null && <StudyCalendar cards={cards}/>}<section className="context-panel"><h3>{t('即将到来的复习')}</h3>{cardRead.data === null && <p className="muted">{t('读取复习卡后显示日历与安排。')}</p>}{cards.filter(card=>(parseInstant(card.due_at)?.getTime() ?? NaN)>now).sort((a,b)=>parseInstant(a.due_at)-parseInstant(b.due_at)).slice(0,5).map(card=><div className="upcoming-card" key={card.id}><strong>{card.prompt}</strong><small>{dates.dateTime(card.due_at)}</small></div>)}{cardRead.data !== null && !cardRead.loading && !cardRead.error && !cards.some(card=>(parseInstant(card.due_at)?.getTime() ?? NaN)>now)&&<p className="muted">{t('暂无记录')}</p>}</section><section className="context-panel" aria-label={t('我的计划')} aria-busy={planRead.loading}><h3>{t("我的计划")}</h3>
      <button className="text-button" disabled={busy || planRead.loading} onClick={planRead.refresh}>{t('刷新学习计划')}</button>
      {planRead.loading && <LoadingState label={t('正在读取学习计划…')} />}
      <FeedbackBlock error={planRead.error ? t('学习计划加载失败，请重试。') : ''} onRetry={!busy ? planRead.refresh : undefined} />
      {planRead.error && planRead.data !== null && <p>{t('已有计划可能不是最新状态。')}</p>}
      {plans.length ? <ul className="plain-list">{plans.map(plan => <li key={plan.id}><strong>{plan.title}</strong><p>{plan.goal}</p><small className="muted">{plan.target_date ? dates.calendarDate(plan.target_date) : t("未设置截止日")}</small></li>)}</ul> : planRead.data !== null && !planRead.loading && !planRead.error && <p className="muted">{t("还没有计划。")}</p>}<h3>{t("复习方法")}</h3><p className="muted">{t("根据你的 0–5 评分、历史间隔和学习结果调整下次到期日。这里不估算学习时长，也不把评分视为掌握保证。")}</p></section></aside></div>
    <Modal open={open} title={t("制定学习计划")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={create}><FeedbackBlock error={error} />{receiptCheck}<label>{t("计划名称")}<input disabled={busy || !!pending} required maxLength={120} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label><label>{t("学习目标")}<textarea disabled={busy || !!pending} required value={form.goal} onChange={e => setForm({ ...form, goal: e.target.value })} /></label><label>{t("目标日期")}<input disabled={busy || !!pending} type="date" value={form.target_date} onChange={e => setForm({ ...form, target_date: e.target.value })} /></label><h3>{t("添加一张复习卡（可选）")}</h3><label>{t("问题")}<textarea disabled={busy || !!pending} maxLength={10000} value={form.prompt} onChange={e => setForm({ ...form, prompt: e.target.value })} /></label><label>{t("参考答案")}<textarea disabled={busy || !!pending} required={!!form.prompt.trim()} maxLength={10000} value={form.answer} onChange={e => setForm({ ...form, answer: e.target.value })} /></label><button className="primary-button" disabled={busy || !!pending}>{busy ? t("创建中…") : t("创建计划")}</button></form></Modal>
  </div>
}
