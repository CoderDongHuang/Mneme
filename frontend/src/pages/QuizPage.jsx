import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, Flag, Lightbulb, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/client'
import { FeedbackBlock, Modal, PageHeader, StatusPill } from '../components/ui'

import { MetricCards } from '../components/ReferenceUI'

function json(value, fallback = []) { try { return typeof value === 'string' ? JSON.parse(value) : value || fallback } catch { return fallback } }
export default function QuizPage() {
  const dates = useDateFormatter()
  useI18n();
  const [quizzes, setQuizzes] = useState([])
  const [bases, setBases] = useState([])
  const [selected, setSelected] = useState(null)
  const [answers, setAnswers] = useState([])
  const [index, setIndex] = useState(0)
  const [attempts, setAttempts] = useState([])
  const [result, setResult] = useState(null)
  const [hint, setHint] = useState(false)
  const [ready, setReady] = useState(false)
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState(false)
  const [reason, setReason] = useState('')
  const [form, setForm] = useState({ kb_id: '', topic: '' })
  const lock = useRef(false)
  const selection = useRef(0)
  const draftChain = useRef(Promise.resolve())
  const currentDraft = useRef(null)
  const draftTimer = useRef(null)
  const submission = useRef(null)
  function enqueueDraft(draft, update = true) {
    const request = draftChain.current.catch(() => {}).then(() => endpoints.saveQuizDraft(draft.id, draft.body))
    draftChain.current = request
    return request.then(() => { if (update && selection.current === draft.version) { setSaved(t("草稿已保存")); setError('') } }).catch(e => { if (update && selection.current === draft.version) { setSaved(t("草稿保存失败")); setError(e.message) } })
  }
  useEffect(() => {
    let active = true
    const selectionState = selection
    Promise.allSettled([endpoints.quizzes(), endpoints.knowledgeBases()]).then(results => {
      if (!active) return
      if (results[0].status === 'fulfilled') setQuizzes(results[0].value || [])
      if (results[1].status === 'fulfilled') { setBases(results[1].value || []); setForm(current => ({ ...current, kb_id: String(results[1].value?.[0]?.id || '') })) }
      setError(results.filter(r => r.status === 'rejected').map(r => r.reason.message).join(' · '))
    })
    return () => { active = false; selectionState.current++; clearTimeout(draftTimer.current); const draft = currentDraft.current; if (draft) void enqueueDraft(draft, false) }
  }, [])
  useEffect(() => {
    if (!ready || !selected || result) { currentDraft.current = null; return }
    const draft = { id: selected.id, version: selection.current, body: { answers, current_question: index } }
    currentDraft.current = draft; setSaved(t("正在保存草稿…"))
    draftTimer.current = setTimeout(() => { void enqueueDraft(draft) }, 500)
    return () => clearTimeout(draftTimer.current)
  }, [answers, index, ready, selected, result])
  async function choose(quiz) {
    if (busy) return
    clearTimeout(draftTimer.current)
    const previous = currentDraft.current
    if (previous) await enqueueDraft(previous)
    const version = ++selection.current
    submission.current = null
    setReady(false); setSelected(quiz); setResult(null); setAnswers([]); setIndex(0); setHint(false); setAttempts([]); setError('')
    try {
      await draftChain.current.catch(() => {})
      const [draft, history] = await Promise.all([endpoints.quizDraft(quiz.id), endpoints.quizAttempts(quiz.id)])
      if (selection.current !== version) return
      setAnswers(json(draft.answers_json)); setIndex(draft.current_question || 0); setAttempts(history || []); setReady(true)
    } catch (e) { if (selection.current === version) setError(e.message) }
  }
  async function run(action) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e.message) } finally { lock.current = false; setBusy(false) }
  }
  const questions = json(selected?.questions_json)
  const question = questions[index]
  const feedback = result?.feedback?.[index]
  function move(next) { setIndex(next); setHint(false) }
  async function submit() {
    await run(async () => {
      clearTimeout(draftTimer.current)
      if (currentDraft.current) await enqueueDraft(currentDraft.current)
      await draftChain.current
      const fingerprint = JSON.stringify(answers)
      if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, id: crypto.randomUUID() }
      const data = await endpoints.submitQuiz(selected.id, answers, submission.current.id)
      currentDraft.current = null; setResult(data); setSaved(t("测验已提交"))
      try { setAttempts(await endpoints.quizAttempts(selected.id)) } catch { setNotice(t("测验已提交，历史记录暂时无法刷新")) }
    })
  }
  return <div className="standard-page reference-page reference-quiz"><PageHeader eyebrow={t("用问题检验理解")} title={t("知识测验")} description={t("围绕你的资料生成题目，回答后查看解释与原文依据。")}><button className="primary-button" onClick={() => setOpen(true)}><Plus size={17} />{t("创建测验")}</button></PageHeader>
    <FeedbackBlock error={error} message={notice} />
    <div className="quiz-workspace"><div className="study-main"><nav className="quiz-selection"><h3>{t("我的测验")}</h3>{quizzes.map(quiz => <button disabled={busy} className={selected?.id === quiz.id ? 'active' : ''} key={quiz.id} onClick={() => choose(quiz)}>{quiz.title}<small>{dates.date(quiz.created_at)}</small></button>)}{!quizzes.length && <p className="muted">{t("还没有测验。")}</p>}</nav><MetricCards items={[{label:t('我的测验'),value:quizzes.length},{label:t('当前题目'),value:questions.length},{label:t('已作答'),value:answers.filter(answer=>answer?.trim()).length}]} />
      <section className="study-card">{!selected ? <div className="empty-state"><CheckCircle2 size={34} /><h2>{t("给知识一次回应")}</h2><p>{t("选择已有测验，或从资料库创建新测验。答案会保存为个人草稿。")}</p><button onClick={() => setOpen(true)}>{t("创建测验")}</button></div> : !ready ? <div className="empty-state"><p>{t("正在恢复测验草稿…")}</p>{error && <button onClick={() => choose(selected)}>{t("重试")}</button>}</div> : question ? <>
        <div className="action-row"><StatusPill>{result ? t("已提交") : t("作答中")}</StatusPill><span className="muted" role="status">{t("第 ")}{index + 1} / {questions.length}{t(" 题 · ")}{saved}</span></div><progress value={index + 1} max={questions.length} aria-label={t("答题进度")} />
        <h2>{question.prompt}</h2>
        <fieldset className="quiz-options" disabled={busy || !!result}><legend className="sr-only">{t("你的答案")}</legend>{Array.isArray(question.options) && question.options.length ? question.options.map((option, number) => { const text = typeof option === 'object' ? (option.text || option.label || JSON.stringify(option)) : option; const value = typeof option === 'object' ? String(option.value ?? option.key ?? text) : String(number); return <label key={number} className={answers[index] === value ? 'selected' : ''}><input type="radio" name={`question-${selected.id}-${index}`} checked={answers[index] === value} onChange={() => setAnswers(current => Array.from({ length: questions.length }, (_, i) => i === index ? value : current[i] || ''))} /><span>{text}</span></label> }) : <textarea aria-label={t("你的答案")} rows={6} maxLength={10000} value={answers[index] || ''} onChange={e => setAnswers(current => Array.from({ length: questions.length }, (_, i) => i === index ? e.target.value : current[i] || ''))} />}</fieldset>
        <div className="action-row"><button className="text-button" onClick={() => setHint(!hint)}><Lightbulb size={16} />{hint ? t("收起提示") : t("查看提示")}</button><button className="text-button" onClick={() => { setReason(''); setReport(true) }}><Flag size={16} />{t("报告题目问题")}</button></div>{hint && <p className="hint-panel">{question.hint || t("试着回忆原文中的概念、条件和例子。")}</p>}
        {feedback && <div className="answer-panel" role="status"><StatusPill tone={feedback.correct ? 'success' : 'warning'}>{feedback.correct ? t("回答正确") : t("需要巩固")}</StatusPill><h3>{t("参考答案")}</h3><p className="preserve-space">{feedback.expected}</p><h3>{t("原文依据")}</h3><p>{feedback.evidence}</p>{feedback.source?.document_id && <Link className="text-link" to={`/workspace?document=${String(feedback.source.document_id).replace(/^doc_/, '')}&page=${feedback.source.page || 1}`}>{t("查看来源原文 →")}</Link>}</div>}
        <footer className="question-controls"><button disabled={index === 0 || busy} onClick={() => move(index - 1)}><ChevronLeft size={17} />{t("上一题")}</button>{index < questions.length - 1 ? <button disabled={busy} onClick={() => move(index + 1)}>{answers[index] ? t("下一题") : t("跳过此题")}<ChevronRight size={17} /></button> : !result && <button className="primary-button" disabled={busy} onClick={submit}>{busy ? t("提交中…") : t("提交测验（已答 {0} 题）", [answers.filter(a => a?.trim()).length])}</button>}</footer>
        {result && <p role="status">{t("本次原始得分 ")}{result.raw_score ?? result.score}{t(" / 100 · 校准得分 ")}{result.score}{t(" / 100。错题已加入复习记录。")}<Link className="text-link" to="/review">{t("去复习 →")}</Link></p>}
      </> : <p>{t("此测验暂无题目。")}</p>}</section></div>
      <aside className="context-panel"><h3>{t("作答记录")}</h3>{attempts.length ? <ul className="plain-list">{attempts.map(attempt => <li key={attempt.id}><button className="text-button" disabled={busy} onClick={() => { clearTimeout(draftTimer.current); currentDraft.current = null; selection.current++; setResult({ score: attempt.score, raw_score: attempt.raw_score, feedback: json(attempt.feedback_json) }); setAnswers(json(attempt.answers_json)); setIndex(0) }}>{attempt.score} / 100 · {dates.dateTime(attempt.created_at)}</button></li>)}</ul> : <p className="muted">{t("提交后会在这里保留历史记录。")}</p>}<h3>{t("评价说明")}</h3><p className="muted">{t("简答题按关键点覆盖评分，选择题按选项匹配。结果用于安排复习，不代表专业认证。")}</p>{result && selected && <button onClick={() => choose(selected)}>{t("重新作答")}</button>}</aside></div>
    <Modal open={open} title={t("创建知识测验")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={e => { e.preventDefault(); run(async () => { const quiz = await endpoints.generateQuiz(form); setQuizzes(items => [quiz, ...items]); setOpen(false); await choose(quiz) }) }}><FeedbackBlock error={error} /><label>{t("资料库")}<select required value={form.kb_id} onChange={e => setForm({ ...form, kb_id: e.target.value })}><option value="">{t("选择资料库")}</option>{bases.map(base => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label><label>{t("测验主题")}<input required maxLength={200} value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} /></label><p className="muted">{t("需要可用的模型与已完成索引的资料。生成失败时会保留输入。")}</p><button className="primary-button" disabled={busy || !bases.length}>{busy ? t("生成中…") : t("生成题目")}</button></form></Modal>
    <Modal open={report} title={t("报告题目问题")} busy={busy} onClose={() => setReport(false)}><form className="form-stack" onSubmit={e => { e.preventDefault(); run(async () => { await endpoints.reportQuestion(selected.id, { question: index, reason }); setReport(false); setNotice(t("问题已记录，感谢反馈")) }) }}><FeedbackBlock error={error} /><label>{t("问题说明")}<textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy}>{t("提交反馈")}</button></form></Modal>
  </div>
}
import '../styles/reference-pages.css'
