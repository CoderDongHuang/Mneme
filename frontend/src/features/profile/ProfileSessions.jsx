import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'
import LoadingState from '../../components/LoadingState'
import { FeedbackBlock } from '../../components/ui'
import { t, useI18n } from '../../i18n'
import { formatDateTime } from '../../utils/dates'

export default function ProfileSessions({ language, timezone, disabled = false }) {
  useI18n()
  const [sessions, setSessions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [revoking, setRevoking] = useState(false)
  const actionLock = useRef(false)
  const alive = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let active = true
    endpoints.authSessions().then(items => {
      if (active) { setSessions(items || []); setLoadError(''); setLoading(false) }
    }).catch(error => {
      if (active) { setLoadError(error.message); setLoading(false) }
    })
    return () => { active = false }
  }, [revision])

  function refresh() {
    setLoading(true); setLoadError(''); setRevision(value => value + 1)
  }
  async function revoke(id) {
    if (actionLock.current || loading || disabled) return
    actionLock.current = true
    setRevoking(true); setActionError(''); setNotice('')
    try {
      await endpoints.revokeAuthSession(id)
      if (alive.current) {
        // The mutation succeeded even if the following list refresh fails.
        setSessions(items => items.filter(item => item.session_id !== id))
        setNotice(t('会话已撤销'))
        refresh()
      }
    } catch (error) { if (alive.current) setActionError(error.message) }
    finally {
      actionLock.current = false
      if (alive.current) setRevoking(false)
    }
  }

  return <section className="profile-form" aria-labelledby="profile-sessions-title" aria-busy={loading || revoking}>
    <h2 id="profile-sessions-title">{t('登录会话')}</h2>
    <p className="muted">{t('撤销会话后，对应设备的登录凭证立即失效；撤销当前会话需要重新登录。')}</p>
    <FeedbackBlock error={loadError ? `${t('登录会话加载失败：')}${loadError}` : ''} onRetry={refresh} />
    {loadError && sessions !== null && <p role="status">{t('已有会话记录可能不是最新状态。')}</p>}
    <FeedbackBlock error={actionError} message={notice} />
    {loading && <LoadingState label={t('正在读取登录会话')} />}
    {sessions?.length > 0 && <ul className="plain-list">{sessions.map(item => <li key={item.session_id}>
      <strong>{item.remembered ? t('长期登录') : t('普通登录')}</strong>
      <small>{t('最近活动：')}{formatDateTime(item.last_seen_at, language, timezone)}</small>
      <button disabled={disabled || loading || revoking} onClick={() => revoke(item.session_id)}>{t('撤销会话')}</button>
    </li>)}</ul>}
    {!loading && !loadError && sessions?.length === 0 && <p>{t('暂无活动会话。')}</p>}
  </section>
}
