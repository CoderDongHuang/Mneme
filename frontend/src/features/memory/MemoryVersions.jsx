import { useEffect, useState } from 'react'
import { endpoints } from '../../api/client'
import { FeedbackBlock } from '../../components/ui'
import { useFormatters } from '../../hooks/useFormatters'
import { t, useI18n } from '../../i18n'

export default function MemoryVersions({ memoryId, revision, busy, onRestore }) {
  useI18n()
  const fmt = useFormatters()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ items: [], loaded: false, loading: true, error: false })
  useEffect(() => {
    let active = true
    async function load() {
      setState(old => ({ ...old, loading: true, error: false }))
      try {
        const data = await endpoints.memoryVersions(memoryId)
        if (active) setState({ items: data.versions || [], loaded: true, loading: false, error: false })
      } catch {
        if (active) setState(old => ({ ...old, loading: false, error: true }))
      }
    }
    void load()
    return () => { active = false }
  }, [memoryId, revision, attempt])
  return <details><summary>{t('历史版本')}{state.loaded ? ` (${fmt.number(state.items.length)})` : ''}</summary>
    <section aria-label={t('记忆历史版本')} aria-busy={state.loading}>
      {state.loading && <p role="status">{t('正在读取记忆版本…')}</p>}
      <FeedbackBlock error={state.error ? t('记忆版本加载失败，请重试。') : ''} onRetry={state.error && !busy ? () => {
        setState(old => ({ ...old, loading: true, error: false }))
        setAttempt(value => value + 1)
      } : undefined} />
      {state.error && state.loaded && <p>{t('已有版本记录可能不是最新状态。')}</p>}
      {state.loaded && !state.loading && !state.error && !state.items.length && <p>{t('暂无历史版本。')}</p>}
      <ul className="plain-list">{state.items.map(version => <li key={version.version}>
        <p>{t('版本 ')}{fmt.number(version.version)} · {version.reason || version.action}</p><p>{version.content}</p>
        <button disabled={busy || state.loading || state.error} onClick={() => onRestore(version.version)}>{t('恢复此版本')}</button>
      </li>)}</ul>
    </section>
  </details>
}
