import { useEffect, useState } from 'react'
import { endpoints } from '../../api/client'
import { FeedbackBlock } from '../../components/ui'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { useFormatters } from '../../hooks/useFormatters'
import { t, useI18n } from '../../i18n'

export default function QuizAttempts({ quizId, revision, busy, onChoose }) {
  useI18n()
  const fmt = useFormatters()
  const dates = useDateFormatter()
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState({ items: null, loading: true, error: '' })
  useEffect(() => {
    let active = true
    setState(old => ({ ...old, loading: true, error: '' }))
    endpoints.quizAttempts(quizId).then(items => {
      if (active) setState({ items: items || [], loading: false, error: '' })
    }).catch(error => {
      if (active) setState(old => ({ ...old, loading: false, error: error.message }))
    })
    return () => { active = false }
  }, [quizId, revision, retry])
  return <section aria-label={t('作答记录')} aria-busy={state.loading}>
    <h3>{t('作答记录')}</h3>
    {state.loading && <p role="status">{t('正在读取作答记录…')}</p>}
    <FeedbackBlock error={state.error ? t('作答记录加载失败：{0}', [state.error]) : ''} onRetry={state.error && !busy ? () => setRetry(value => value + 1) : undefined} />
    {state.error && state.items !== null && <p>{t('已有作答记录可能不是最新状态。')}</p>}
    {state.items?.length ? <ul className="plain-list">{state.items.map(attempt => <li key={attempt.id}>
      <button className="text-button" disabled={busy} onClick={() => onChoose(attempt)}>{fmt.number(attempt.score)} / 100 · {dates.dateTime(attempt.created_at)}</button>
    </li>)}</ul> : state.items !== null && !state.loading && !state.error && <p className="muted">{t('提交后会在这里保留历史记录。')}</p>}
  </section>
}
