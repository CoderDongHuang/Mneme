import { useCallback, useEffect, useRef } from 'react'
import useIndependentRead from '../../hooks/useIndependentRead'
import { validAttempts } from './quizValidation'
import { endpoints } from '../../api/client'
import { FeedbackBlock } from '../../components/ui'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { useFormatters } from '../../hooks/useFormatters'
import { t, useI18n } from '../../i18n'

export default function QuizAttempts({ quizId, questionCount, revision, busy, onChoose }) {
  useI18n()
  const fmt = useFormatters()
  const dates = useDateFormatter()
  const read = useCallback(options => endpoints.quizAttempts(quizId, options), [quizId])
  const valid = useCallback(value => validAttempts(value, questionCount), [questionCount])
  const state = useIndependentRead(read, valid)
  const { invalidate, refresh } = state
  const previous = useRef(revision)
  useEffect(() => {
    if (previous.current !== revision) { previous.current = revision; invalidate(); void refresh() }
  }, [revision, invalidate, refresh])
  return <section aria-label={t('作答记录')} aria-busy={state.loading}>
    <h3>{t('作答记录')}</h3>
    {state.loading && <p role="status">{t('正在读取作答记录…')}</p>}
    <FeedbackBlock error={state.error ? t('作答记录加载失败，请重试。') : ''} onRetry={state.error && !busy ? state.refresh : undefined} />
    {state.error && state.data !== null && <p>{t('已有作答记录可能不是最新状态。')}</p>}
    {state.data?.length ? <ul className="plain-list">{state.data.map(attempt => <li key={attempt.id}>
      <button className="text-button" disabled={busy || state.loading || state.error} onClick={() => onChoose(attempt)}>{fmt.number(attempt.score)} / 100 · {dates.dateTime(attempt.created_at)}</button>
    </li>)}</ul> : state.data !== null && !state.loading && !state.error && <p className="muted">{t('提交后会在这里保留历史记录。')}</p>}
  </section>
}
