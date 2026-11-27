import { useEffect, useState } from 'react'
import { endpoints } from '../../api/client'
import { FeedbackBlock, Modal } from '../../components/ui'
import LoadingState from '../../components/LoadingState'
import StatusBadge from '../../components/StatusBadge'
import { useDateFormatter } from '../../hooks/useDateFormatter'
import { t, useI18n } from '../../i18n'
import { validDocumentVersions } from './previewValidation'

export default function DocumentVersions({ document, busy, unavailable, onClose, onRestore }) {
  useI18n()
  const dates = useDateFormatter()
  const { id } = document
  const revision = JSON.stringify([id, document.updatedAt, document.status, document.fileName])
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ revision, items: null, loading: true, error: false })
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    async function load() {
      setState(old => ({ ...old, loading: true, error: false }))
      try {
        const items = await endpoints.documentVersions(id, { signal: controller.signal })
        if (!validDocumentVersions(items)) throw new Error('Invalid document versions')
        if (active) setState({ revision, items, loading: false, error: false })
      } catch {
        if (active) setState(old => ({ ...old, revision, loading: false, error: true }))
      }
    }
    void load()
    return () => { active = false; controller.abort() }
  }, [id, revision, attempt])
  const loading = state.loading || state.revision !== revision
  const blocked = loading || state.error || unavailable || busy
  return <Modal title={t('版本历史')} onClose={onClose} busy={busy}>
    <section className="version-dialog" aria-label={t('文档版本读取')} aria-busy={loading}>
      <h3>{document.fileName}</h3>
      {loading && <LoadingState label={t('正在读取版本')} />}
      <FeedbackBlock error={state.error ? t('文档版本加载失败，请重试。') : ''}
        onRetry={state.error && !loading && !busy ? () => {
          setState(old => ({ ...old, loading: true, error: false }))
          setAttempt(value => value + 1)
        } : undefined} />
      {state.error && state.items !== null && <p>{t('已有版本记录可能不是最新状态。')}</p>}
      {!loading && !state.error && state.items?.length === 0 && <p>{t('暂无历史版本。')}</p>}
      <div className="version-list">{state.items?.map(version => (
        <button key={version.version_number} disabled={blocked || Boolean(version.active)} onClick={() => onRestore(version)}>
          <span>
            <strong>v{version.version_number} · {version.file_name ?? document.fileName}</strong>
            <small>{version.sha256?.slice(0, 12) || '—'} · {dates.dateTime(version.created_at)}</small>
          </span>
          <StatusBadge status={version.active ? 'active' : 'ready'} />
        </button>
      ))}</div>
    </section>
  </Modal>
}
