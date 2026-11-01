import { useEffect, useState } from 'react'
import { endpoints } from '../../api/client'
import { FeedbackBlock } from '../../components/ui'
import LoadingState from '../../components/LoadingState'
import { useFormatters } from '../../hooks/useFormatters'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { t, useI18n } from '../../i18n'

export default function PrivacyOperations({ revision }) {
  useI18n()
  const fmt = useFormatters()
  const dates = useDateFormatter()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ items: null, loading: true, error: '' })
  useEffect(() => {
    let active = true
    setState(old => ({ ...old, loading: true, error: '' }))
    endpoints.operations().then(items => {
      if (active) setState({ items, loading: false, error: '' })
    }).catch(error => {
      if (active) setState(old => ({ ...old, loading: false, error: error.message }))
    })
    return () => { active = false }
  }, [revision, attempt])
  return <section aria-labelledby="privacy-operations-title" aria-busy={state.loading}>
    <h2 id="privacy-operations-title">{t('审计记录')}</h2>
    {state.loading && <LoadingState label={t('正在读取审计记录')} />}
    <FeedbackBlock error={state.error ? `${t('审计记录加载失败：')}${state.error}` : ''} onRetry={() => setAttempt(value => value + 1)} />
    {state.error && state.items !== null && <p>{t('已有审计记录可能不是最新状态。')}</p>}
    {state.items?.length > 0 && <ul className="center-list">{state.items.map((item, index) => <li key={`${item.operation_id}-${index}`}>
      <strong>{item.operation_type}</strong> · {item.step} · {fmt.status(item.status)}<time>{dates.dateTime(item.created_at)}</time>
    </li>)}</ul>}
    {!state.loading && !state.error && state.items?.length === 0 && <p>{t('暂无记录')}</p>}
  </section>
}
