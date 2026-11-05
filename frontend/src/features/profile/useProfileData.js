import { useCallback, useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'
import { t } from '../../i18n'
import { validProfile } from './profileValidation'

const rejected = failure => [400, 401, 403, 404, 405, 413, 415, 422, 429].includes(failure.status)

// A read used for reconciliation never overwrites the editable draft. A lost
// acknowledgement must not silently turn into another PATCH, upload or email.
export default function useProfileData(owner, updateSession) {
  const userId = owner?.userId, username = owner?.username
  const [profile, setDraft] = useState(null)
  const [saved, setSaved] = useState(null)
  const [loading, setLoading] = useState(true)
  const [readError, setReadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)
  const [checked, setChecked] = useState(null)
  const [avatarVersion, setAvatarVersion] = useState(Date.now)
  const active = useRef(false), request = useRef(null), uncertain = useRef(false)

  const accept = useCallback((value, keepDraft = false) => {
    setSaved(value)
    setDraft(current => keepDraft ? { ...value, nickname: current.nickname, email: current.email } : value)
    setAvatarVersion(version => Math.max(Date.now(), version + 1))
  }, [])

  const load = useCallback(async () => {
    if (!active.current || request.current) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setReadError(''); setChecked(null)
    try {
      const value = await endpoints.profile({ signal: controller.signal })
      if (!validProfile(value, { userId, username })) throw new Error(t('个人资料响应格式不正确'))
      if (controller.signal.aborted) return
      if (uncertain.current) setChecked(value)
      else accept(value)
    } catch (failure) {
      if (!controller.signal.aborted) setReadError(failure.message || t('请求失败'))
    } finally {
      if (!controller.signal.aborted) { request.current = null; setLoading(false) }
    }
  }, [accept, userId, username])

  useEffect(() => {
    active.current = true
    void load()
    return () => { active.current = false; request.current?.abort(); request.current = null }
  }, [load])

  function setProfile(value) {
    if (!request.current && !uncertain.current) setDraft(value)
  }

  function resolve(adopt) {
    if (request.current || !uncertain.current || !checked) return
    accept(checked, !adopt); updateSession({ ...checked, avatarVersion: Date.now() })
    uncertain.current = false
    setPending(false); setChecked(null); setReadError(''); setError('')
  }

  async function run(action, success, { profileResult = false, valid = () => true, onSuccess, protect = false } = {}) {
    if (!active.current || request.current || uncertain.current) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true); setError(''); setNotice('')
    try {
      const value = await action({ signal: controller.signal })
      if (controller.signal.aborted) return
      if ((profileResult && !validProfile(value, owner)) || !valid(value)) throw new Error(t('个人资料响应格式不正确'))
      if (profileResult) { accept(value); updateSession({ ...value, avatarVersion: Date.now() }) }
      onSuccess?.(value)
      setNotice(success)
    } catch (failure) {
      if (!controller.signal.aborted) {
        if (protect && !rejected(failure)) {
          uncertain.current = true
          setPending(true); setChecked(null)
          setError(t('资料操作结果尚未确认，请先核对服务端资料。'))
        } else setError(failure.message || t('请求失败'))
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false) }
    }
  }

  return { profile, setProfile, saved, loading, readError, error, setError, notice, busy, pending, checked, avatarVersion, load, resolve, run }
}
