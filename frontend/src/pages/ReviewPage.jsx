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
import '../styles/reference-pages.css'

export default function ReviewPage() {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n();
  const { cards: cardRead, plans: planRead } = useReviewData()
  const cards = cardRead.items || []
  const plans = planRead.items || []
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [flippedId, setFlippedId] = useState(null)
  const [selected, setSelected] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
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
    if (!current || !flipped || lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try {
      const saved = await endpoints.reviewCard(current.id, rating)
      if (alive.current) {
        cardRead.replace(saved); setFlippedId(null); setSelected(null)
        setNotice(t("评分已保存，下次复习：{0}", [dates.dateTime(saved.due_at)]))
      }
    } catch (e) { if (alive.current) setError(e.message) } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  async function create(event) {
    event.preventDefault(); if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try {
      await endpoints.createPlan({ title: form.title, goal: form.goal, target_date: form.target_date, cards: form.prompt.trim() ? [{ prompt: form.prompt, answer: form.answer }] : [] })
      if (alive.current) {
        setOpen(false); setForm({ title: '', goal: '', target_date: '', prompt: '', answer: '' })
        setNotice(t("计划已创建，复习卡使用你填写的真实答案"))
        void cardRead.refresh(); void planRead.refresh()
      }
    } catch (e) { if (alive.current) setError(e.message) } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  return <div className="standard-page reference-page reference-review">
    <PageHeader eyebrow={t("循序渐进")} title={t("复习计划")} description={t("从今天的一张卡片开始，把理解留得更久。")}><button className="primary-button" disabled={busy} onClick={() => { setError(''); setOpen(true) }}><Plus size={17} />{t("制定计划")}</button></PageHeader>
    <FeedbackBlock error={open ? '' : error} message={notice} />
    <div className="study-layout"><div className="study-main"><MetricCards items={[{label:t('今日待复习'),value:cardRead.items === null ? '—' : due.length,icon:Clock},{label:t('已复习卡片'),value:cardRead.items === null ? '—' : cards.filter(card=>card.review_count>0).length,icon:CheckCircle2},{label:t('学习计划'),value:planRead.items === null ? '—' : plans.length,icon:CalendarDays}]} /><section className="study-card" aria-label={t('复习卡片')} aria-busy={cardRead.loading} aria-live="polite">
      {cardRead.loading && <LoadingState label={t('正在读取复习卡…')} />}
      <FeedbackBlock error={cardRead.error ? `${t('复习卡加载失败：')}${cardRead.error}` : ''} onRetry={!busy ? cardRead.refresh : undefined} />
      {cardRead.error && cardRead.items !== null && <p>{t('已有复习卡可能不是最新状态。')}</p>}
      {current ? <><div className="action-row"><StatusPill>{current.origin === 'quiz_mistake' ? t("错题巩固") : t("学习卡片")}</StatusPill><span className="muted">{t("待复习 ")}{fmt.integer(due.length)}{t(" · 已复习 ")}{fmt.integer(current.review_count ?? 0)}{t(" 次")}</span></div><h2>{current.prompt}</h2><p className="muted">{t("先回忆，再翻面核对。评分决定下一次复习时间。")}</p>{flipped ? <div className="answer-panel"><h3>{t("参考答案")}</h3><p className="preserve-space">{current.answer}</p></div> : <button className="flip-button" onClick={() => setFlippedId(current.id)}><RotateCcw size={18} />{t("查看答案")}</button>}{flipped && <div className="rating-actions" aria-label={t("复习评分")}>{[[0, t("忘记了")], [3, t("有些困难")], [4, t("基本掌握")], [5, t("很轻松")]].map(([rating, label]) => <button key={rating} disabled={busy} onClick={() => rate(rating)}>{t(label)}</button>)}</div>}{due.length > 1 && <button className="text-button" disabled={busy} onClick={() => { const index = due.findIndex(card => card.id === current.id); setSelected(due[(index + 1) % due.length].id); setFlippedId(null) }}>{t("暂时跳过")}</button>}</> : cardRead.items !== null && !cardRead.loading && !cardRead.error && <div className="empty-state"><CalendarDays size={32} /><h2>{t("今天的复习已就绪")}</h2><p>{t("当前没有到期卡片。你可以制定计划，或通过测验生成错题卡。")}</p><Link to="/quiz" className="text-link">{t("开始一次测验 →")}</Link></div>}
    </section></div><aside className="study-sidebar">{cardRead.items !== null && <StudyCalendar cards={cards}/>}<section className="context-panel"><h3>{t('即将到来的复习')}</h3>{cardRead.items === null && <p className="muted">{t('读取复习卡后显示日历与安排。')}</p>}{cards.filter(card=>(parseInstant(card.due_at)?.getTime() ?? NaN)>now).sort((a,b)=>parseInstant(a.due_at)-parseInstant(b.due_at)).slice(0,5).map(card=><div className="upcoming-card" key={card.id}><strong>{card.prompt}</strong><small>{dates.dateTime(card.due_at)}</small></div>)}{cardRead.items !== null && !cardRead.loading && !cardRead.error && !cards.some(card=>(parseInstant(card.due_at)?.getTime() ?? NaN)>now)&&<p className="muted">{t('暂无记录')}</p>}</section><section className="context-panel" aria-label={t('我的计划')} aria-busy={planRead.loading}><h3>{t("我的计划")}</h3>
      {planRead.loading && <LoadingState label={t('正在读取学习计划…')} />}
      <FeedbackBlock error={planRead.error ? `${t('学习计划加载失败：')}${planRead.error}` : ''} onRetry={!busy ? planRead.refresh : undefined} />
      {planRead.error && planRead.items !== null && <p>{t('已有计划可能不是最新状态。')}</p>}
      {plans.length ? <ul className="plain-list">{plans.map(plan => <li key={plan.id}><strong>{plan.title}</strong><p>{plan.goal}</p><small className="muted">{plan.target_date ? dates.calendarDate(plan.target_date) : t("未设置截止日")}</small></li>)}</ul> : planRead.items !== null && !planRead.loading && !planRead.error && <p className="muted">{t("还没有计划。")}</p>}<h3>{t("复习方法")}</h3><p className="muted">{t("根据你的 0–5 评分、历史间隔和学习结果调整下次到期日。这里不估算学习时长，也不把评分视为掌握保证。")}</p></section></aside></div>
    <Modal open={open} title={t("制定学习计划")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={create}><FeedbackBlock error={error} /><label>{t("计划名称")}<input disabled={busy} required maxLength={120} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></label><label>{t("学习目标")}<textarea disabled={busy} required value={form.goal} onChange={e => setForm({ ...form, goal: e.target.value })} /></label><label>{t("目标日期")}<input disabled={busy} type="date" value={form.target_date} onChange={e => setForm({ ...form, target_date: e.target.value })} /></label><h3>{t("添加一张复习卡（可选）")}</h3><label>{t("问题")}<textarea disabled={busy} maxLength={10000} value={form.prompt} onChange={e => setForm({ ...form, prompt: e.target.value })} /></label><label>{t("参考答案")}<textarea disabled={busy} required={!!form.prompt.trim()} maxLength={10000} value={form.answer} onChange={e => setForm({ ...form, answer: e.target.value })} /></label><button className="primary-button" disabled={busy}>{busy ? t("创建中…") : t("创建计划")}</button></form></Modal>
  </div>
}
