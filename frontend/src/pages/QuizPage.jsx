import { useDateFormatter } from '../hooks/useDateFormatter'
import { useFormatters } from '../hooks/useFormatters'
import { t, useI18n } from '../i18n'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, Flag, Lightbulb, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/client'
import { FeedbackBlock, Modal, PageHeader, StatusPill } from '../components/ui'

import { MetricCards } from '../components/ReferenceUI'
import QuizAttempts from '../features/quiz/QuizAttempts'
import useIndependentRead from '../hooks/useIndependentRead'
import { validBases } from '../api/collectionValidation'
import { quizArray, validDraft, validDraftReceipt, validQuizzes, validQuiz, validSubmission } from '../features/quiz/quizValidation'
import { useAuth } from '../state/AuthContext'

export default function QuizPage() {
  const session = useAuth()?.session
  const owner = session?.userId || session?.username || 'anonymous'
  const currentOwner = useRef(owner)
  useLayoutEffect(() => { currentOwner.current = owner }, [owner])
  return <QuizView key={owner} owner={owner} currentOwner={currentOwner} />
}

function QuizView({ owner, currentOwner }) {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n();
  const quizRead = useIndependentRead(endpoints.quizzes, validQuizzes)
  const baseRead = useIndependentRead(endpoints.knowledgeBases, validBases)
  const quizzes = quizRead.data
  const bases = baseRead.data
  const [selected, setSelected] = useState(null)
  const [answers, setAnswers] = useState([])
  const [index, setIndex] = useState(0)
  const [attemptRevision, setAttemptRevision] = useState(0)
  const [result, setResult] = useState(null)
  const [submissionPending, setSubmissionPending] = useState(false)
  const [generationPending, setGenerationPending] = useState(false)
  const [generationChecked, setGenerationChecked] = useState(false)
  const [hint, setHint] = useState(false)
  const [ready, setReady] = useState(false)
  const [draftError, setDraftError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [open, setOpen] = useState(false)
  const [report, setReport] = useState(false)
  const [reason, setReason] = useState('')
  const [form, setForm] = useState({ kb_id: null, topic: '' })
  const lock = useRef(false)
  const alive = useRef(false)
  const selection = useRef(0)
  const draftChain = useRef(Promise.resolve())
  const currentDraft = useRef(null)
  const draftTimer = useRef(null)
  const submission = useRef(null)
  const draftRead = useRef(null)
  const enqueueDraft = useCallback((draft, update = true) => {
    const request = draftChain.current.catch(() => {}).then(async () => {
      if (currentOwner.current !== owner || (!alive.current && update)) return
      const receipt = await endpoints.saveQuizDraft(draft.id, draft.body)
      if (!validDraftReceipt(receipt, draft.body, draft.count)) throw new Error(t('草稿保存回执无法确认，请重试保存'))
      return receipt
    })
    draftChain.current = request
    return request.then(() => { if (update && alive.current && currentDraft.current === draft) { setSaved(t("草稿已保存")); setSaveError('') } }).catch(e => {
      if (update && alive.current && currentDraft.current === draft) { setSaved(t("草稿保存失败")); setSaveError(e.message) }
      throw e
    })
  }, [owner, currentOwner])
  useEffect(() => {
    alive.current = true
    const selectionState = selection
    return () => { alive.current = false; selectionState.current++; draftRead.current?.abort(); clearTimeout(draftTimer.current); const draft = currentDraft.current; if (draft) void enqueueDraft(draft, false).catch(() => {}) }
  }, [enqueueDraft])
  useEffect(() => {
    if (!ready || !selected || result || submissionPending) { currentDraft.current = null; return }
    const draft = { id: selected.id, count: quizArray(selected.questions_json).length, body: { answers, current_question: index } }
    currentDraft.current = draft; setSaved(t("正在保存草稿…"))
    draftTimer.current = setTimeout(() => { void enqueueDraft(draft).catch(() => {}) }, 500)
    return () => clearTimeout(draftTimer.current)
  }, [answers, index, ready, selected, result, submissionPending, enqueueDraft])
  async function choose(quiz) {
    if (submissionPending) return
    await run(async () => {
      await flushDraft()
      if (alive.current) await loadQuiz(quiz)
    })
  }
  async function flushDraft() {
    clearTimeout(draftTimer.current)
    if (currentDraft.current) await enqueueDraft(currentDraft.current)
    else await draftChain.current.catch(() => {})
  }
  async function loadQuiz(quiz) {
    draftRead.current?.abort()
    const controller = new AbortController()
    draftRead.current = controller
    const version = ++selection.current
    currentDraft.current = null; submission.current = null
    setReady(false); setSelected(quiz); setResult(null); setAnswers([]); setIndex(0); setHint(false); setDraftError(''); setSaveError(''); setSaved('')
    try {
      const draft = await endpoints.quizDraft(quiz.id, { signal: controller.signal })
      if (!validDraft(draft, quizArray(quiz.questions_json).length)) throw new Error()
      if (!alive.current || selection.current !== version) return
      setAnswers(quizArray(draft.answers_json)); setIndex(draft.current_question); setReady(true)
    } catch { if (alive.current && selection.current === version) setDraftError(true) }
  }
  async function run(action) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { if (alive.current) setError(e.message) } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  const questions = selected ? quizArray(selected.questions_json) : []
  const question = questions[index]
  const feedback = result?.feedback?.[index]
  function move(next) { setIndex(next); setHint(false) }
  async function submit() {
    await run(async () => {
      if (!submissionPending) await flushDraft()
      if (!alive.current) return
      const fingerprint = JSON.stringify(answers)
      if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, id: crypto.randomUUID() }
      clearTimeout(draftTimer.current); currentDraft.current = null; setSubmissionPending(true)
      const data = await endpoints.submitQuiz(selected.id, answers, submission.current.id)
      if (!alive.current) return
      if (!validSubmission(data, questions.length)) throw new Error(t('测验提交回执无法确认，请重试确认提交。'))
      setSubmissionPending(false); currentDraft.current = null; setResult(data); setSaved(t("测验已提交"))
      setAttemptRevision(value => value + 1)
    })
  }
  async function generate() {
    if (generationPending || submissionPending || baseRead.loading || baseRead.error || !bases?.length) return
    await run(async () => {
      await flushDraft()
      if (!alive.current) return
      setGenerationPending(true); setGenerationChecked(false)
      const quiz = await endpoints.generateQuiz({ ...form, kb_id: form.kb_id ?? String(bases[0].id) })
      if (!alive.current) return
      if (!validQuiz(quiz)) throw new Error(t('测验创建回执无法确认，请先核对测验列表。'))
      quizRead.commit(items => [quiz, ...items.filter(item => item.id !== quiz.id)])
      setGenerationPending(false); setOpen(false); setNotice(t('测验已创建'))
      await loadQuiz(quiz)
    })
  }
  return <div className="standard-page reference-page reference-quiz"><PageHeader eyebrow={t("用问题检验理解")} title={t("知识测验")} description={t("围绕你的资料生成题目，回答后查看解释与原文依据。")}><button className="primary-button" disabled={busy} onClick={() => setOpen(true)}><Plus size={17} />{t("创建测验")}</button></PageHeader>
    <FeedbackBlock error={error} /><FeedbackBlock message={notice} />{submissionPending && <p role="status">{t("提交结果尚未确认。答案已锁定，重试将沿用同一提交编号，不会重复评分。")}</p>}
    <FeedbackBlock error={saveError ? t('草稿保存失败：{0}。当前答案已保留，请重试保存后再切换。', [saveError]) : ''} onRetry={saveError && !busy ? () => run(flushDraft) : undefined} />
    <div className="quiz-workspace"><div className="study-main"><nav className="quiz-selection" aria-label={t('我的测验')} aria-busy={quizRead.loading}><h3>{t("我的测验")}</h3>
      {quizRead.loading && <p role="status">{t('正在读取测验…')}</p>}
      <FeedbackBlock error={quizRead.error ? t('测验列表加载失败，请重试。') : ''} onRetry={quizRead.error && !busy ? quizRead.refresh : undefined} />
      {quizzes !== null && quizRead.error && <p>{t('已有测验列表可能不是最新状态。')}</p>}
      {(quizzes || []).map(quiz => <button disabled={busy || submissionPending || quizRead.loading || quizRead.error} className={selected?.id === quiz.id ? 'active' : ''} key={quiz.id} onClick={() => choose(quiz)}>{quiz.title}<small>{dates.date(quiz.created_at)}</small></button>)}
      {quizzes !== null && !quizRead.loading && !quizRead.error && !quizzes.length && <p className="muted">{t("还没有测验。")}</p>}
    </nav><MetricCards items={[{label:t('我的测验'),value:quizzes === null ? '—' : quizzes.length},{label:t('当前题目'),value:selected && ready ? questions.length : '—'},{label:t('已作答'),value:selected && ready ? answers.filter(answer=>answer?.trim()).length : '—'}]} />
      <section className="study-card">{!selected ? <div className="empty-state"><CheckCircle2 size={34} /><h2>{t("给知识一次回应")}</h2><p>{t("选择已有测验，或从资料库创建新测验。答案会保存为个人草稿。")}</p><button onClick={() => setOpen(true)}>{t("创建测验")}</button></div> : !ready ? <div className="empty-state"><FeedbackBlock error={draftError ? t('测验草稿加载失败，请重试。') : ''} onRetry={draftError && !busy ? () => choose(selected) : undefined} />{!draftError && <p role="status">{t("正在恢复测验草稿…")}</p>}</div> : question ? <>
        <div className="action-row"><StatusPill>{result ? t("已提交") : t("作答中")}</StatusPill><span className="muted" role="status">{t("第 ")}{fmt.integer(index + 1)} / {fmt.integer(questions.length)}{t(" 题 · ")}{saved}</span></div><progress value={index + 1} max={questions.length} aria-label={t("答题进度")} />
        <h2>{question.prompt}</h2>
        <fieldset className="quiz-options" disabled={busy || !!result || submissionPending}><legend className="sr-only">{t("你的答案")}</legend>{Array.isArray(question.options) && question.options.length ? question.options.map((option, number) => { const text = typeof option === 'object' ? (option.text || option.label || '') : option; const value = typeof option === 'object' ? String(option.value ?? option.key ?? text) : String(number); return <label key={number} className={answers[index] === value ? 'selected' : ''}><input type="radio" name={`question-${selected.id}-${index}`} checked={answers[index] === value} onChange={() => setAnswers(current => Array.from({ length: questions.length }, (_, i) => i === index ? value : current[i] || ''))} /><span>{text}</span></label> }) : <textarea aria-label={t("你的答案")} rows={6} maxLength={10000} value={answers[index] || ''} onChange={e => setAnswers(current => Array.from({ length: questions.length }, (_, i) => i === index ? e.target.value : current[i] || ''))} />}</fieldset>
        <div className="action-row"><button className="text-button" onClick={() => setHint(!hint)}><Lightbulb size={16} />{hint ? t("收起提示") : t("查看提示")}</button><button className="text-button" onClick={() => { setReason(''); setReport(true) }}><Flag size={16} />{t("报告题目问题")}</button></div>{hint && <p className="hint-panel">{question.hint || t("试着回忆原文中的概念、条件和例子。")}</p>}
        {feedback && <div className="answer-panel" role="status"><StatusPill tone={feedback.correct ? 'success' : 'warning'}>{feedback.correct ? t("回答正确") : t("需要巩固")}</StatusPill><h3>{t("参考答案")}</h3><p className="preserve-space">{feedback.expected}</p><h3>{t("原文依据")}</h3><p>{feedback.evidence}</p>{feedback.source?.document_id && <Link className="text-link" to={`/workspace?document=${String(feedback.source.document_id).replace(/^doc_/, '')}&page=${feedback.source.page || 1}`}>{t("查看来源原文 →")}</Link>}</div>}
        <footer className="question-controls"><button disabled={index === 0 || busy} onClick={() => move(index - 1)}><ChevronLeft size={17} />{t("上一题")}</button>{index < questions.length - 1 ? <button disabled={busy} onClick={() => move(index + 1)}>{answers[index] ? t("下一题") : t("跳过此题")}<ChevronRight size={17} /></button> : !result && <button className="primary-button" disabled={busy} onClick={submit}>{busy ? t("提交中…") : t("提交测验（已答 {0} 题）", [fmt.integer(answers.filter(a => a?.trim()).length)])}</button>}</footer>
        {result && <p role="status">{t("本次原始得分 ")}{fmt.number(result.raw_score ?? result.score)}{t(" / 100 · 校准得分 ")}{fmt.number(result.score)}{t(" / 100。错题已加入复习记录。")}<Link className="text-link" to="/review">{t("去复习 →")}</Link></p>}
      </> : <p>{t("此测验暂无题目。")}</p>}</section></div>
      <aside className="context-panel">{selected ? <QuizAttempts key={selected.id} quizId={selected.id} questionCount={questions.length} revision={attemptRevision} busy={busy || submissionPending} onChoose={attempt => run(async () => {
        await flushDraft()
        if (!alive.current) return
        currentDraft.current = null; selection.current++; setReady(true); setDraftError(''); setHint(false)
        setResult({ score: attempt.score, raw_score: attempt.raw_score, feedback: quizArray(attempt.feedback_json) }); setAnswers(quizArray(attempt.answers_json)); setIndex(0)
      })} /> : <><h3>{t('作答记录')}</h3><p>{t('选择测验后查看作答记录。')}</p></>}<h3>{t("评价说明")}</h3><p className="muted">{t("简答题按关键点覆盖评分，选择题按选项匹配。结果用于安排复习，不代表专业认证。")}</p>{result && selected && <button disabled={busy} onClick={() => choose(selected)}>{t("重新作答")}</button>}</aside></div>
    <Modal open={open} title={t("创建知识测验")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={e => { e.preventDefault(); void generate() }}><FeedbackBlock error={error} />{generationPending && <section aria-label={t('核对测验列表')}><p>{t('创建结果尚未确认。请先核对最新列表，再决定是否重新创建；重新创建可能产生另一份测验。')}</p><button type="button" disabled={busy || quizRead.loading} onClick={async () => { setGenerationChecked(false); const items = await quizRead.refresh(); if (items !== undefined) setGenerationChecked(true) }}>{t('核对测验列表')}</button>{quizRead.error && <p role="alert">{t('测验列表加载失败，请重试。')}</p>}{generationChecked && <><ul>{(quizzes || []).map(quiz => <li key={quiz.id}>{quiz.title}</li>)}</ul><button type="button" onClick={() => { setGenerationPending(false); setGenerationChecked(false) }}>{t('已核实，继续操作')}</button></>}</section>}<section aria-label={t('测验资料库')} aria-busy={baseRead.loading}>{baseRead.loading && <p role="status">{t('正在读取资料库…')}</p>}<FeedbackBlock error={baseRead.error ? t('测验资料库加载失败，请重试。') : ''} onRetry={baseRead.error && !busy ? baseRead.refresh : undefined} />{bases !== null && !baseRead.loading && !baseRead.error && !bases.length && <p>{t('暂无可用于测验的资料库。')}</p>}<label>{t("资料库")}<select required value={form.kb_id ?? String(bases?.[0]?.id || '')} onChange={e => setForm({ ...form, kb_id: e.target.value })}><option value="">{t("选择资料库")}</option>{(bases || []).map(base => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label></section><label>{t("测验主题")}<input required maxLength={200} value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} /></label><p className="muted">{t("需要可用的模型与已完成索引的资料。生成失败时会保留输入。")}</p><button className="primary-button" disabled={busy || submissionPending || generationPending || baseRead.loading || !!baseRead.error || !bases?.length}>{busy ? t("生成中…") : t("生成题目")}</button></form></Modal>
    <Modal open={report} title={t("报告题目问题")} busy={busy} onClose={() => setReport(false)}><form className="form-stack" onSubmit={e => { e.preventDefault(); run(async () => { await endpoints.reportQuestion(selected.id, { question: index, reason }); if (!alive.current) return; setReport(false); setNotice(t("问题已记录，感谢反馈")) }) }}><FeedbackBlock error={error} /><label>{t("问题说明")}<textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy}>{t("提交反馈")}</button></form></Modal>
  </div>
}
import '../styles/reference-pages.css'
