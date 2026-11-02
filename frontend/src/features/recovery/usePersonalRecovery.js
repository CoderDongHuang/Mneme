import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'
import { t } from '../../i18n'

const count = value => Number.isSafeInteger(value) && value >= 0
const counts = value => value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(count)
const validPreview = (data, file, scope) => data?.compatible === true && data.mode === 'additive' && data.overwritten === 0
  && data.scope === scope && data.bytes === file.size && Number.isSafeInteger(data.version) && data.version > 0
  && typeof data.created_at === 'string' && typeof data.encrypted === 'boolean'
  && typeof data.sha256 === 'string' && /^[a-f0-9]{64}$/.test(data.sha256) && counts(data.counts)
  && count(data.missing_files) && Array.isArray(data.same_name_libraries) && data.same_name_libraries.every(item => typeof item === 'string')
const validResult = data => data?.status === 'imported' && typeof data.message === 'string' && counts(data.workspace?.counts)
  && count(data.documents?.restored) && count(data.documents?.skipped)

export function usePersonalRecovery() {
  const [file, setFile] = useState(null), [scope, setScope] = useState('all')
  const [preview, setPreview] = useState(null), [result, setResult] = useState(null)
  const [confirmation, setConfirmation] = useState(''), [error, setError] = useState('')
  const [busy, setBusy] = useState(''), [step, setStep] = useState(1), [uncertain, setUncertain] = useState(false)
  const [fileKey, setFileKey] = useState(0)
  const lifetime = useRef(null), request = useRef(null), selection = useRef({ file: null, scope: 'all' }), checked = useRef(null)
  const importing = useRef(false), unknown = useRef(false)
  useEffect(() => {
    const owner = new AbortController(); lifetime.current = owner
    return () => { owner.abort(); request.current?.abort() }
  }, [])
  function clear() {
    request.current?.abort(); request.current = null; checked.current = null
    setPreview(null); setResult(null); setConfirmation(''); setError(''); setBusy(''); setStep(1)
  }
  function chooseFile(value) {
    if (importing.current || unknown.current) return
    clear(); selection.current = { ...selection.current, file: value }; setFile(value)
  }
  function chooseScope(value) {
    if (importing.current || unknown.current) return
    clear(); selection.current = { ...selection.current, scope: value }; setScope(value)
  }
  function reset() {
    if (importing.current) return
    clear(); selection.current = { file: null, scope: 'all' }; setFile(null); setScope('all')
    unknown.current = false; setUncertain(false)
    setFileKey(value => value + 1)
  }
  async function verify() {
    if (importing.current || unknown.current || !selection.current.file) return
    clear()
    const selected = selection.current, controller = new AbortController(), owner = lifetime.current
    request.current = controller; setBusy('preview')
    const current = () => !owner.signal.aborted && !controller.signal.aborted && request.current === controller && selection.current === selected
    try {
      if (selected.file.size > 50 * 1024 * 1024) throw new Error(t('归档不得超过 50 MiB'))
      const data = await endpoints.previewArchive(selected.file, selected.scope, { signal: controller.signal })
      if (!validPreview(data, selected.file, selected.scope)) throw new Error(t('个人归档响应格式不正确，请重新校验。'))
      if (current()) { checked.current = { selection: selected, data }; setPreview(data); setStep(2) }
    } catch (failure) { if (current()) setError(failure.message || t('请求失败')) }
    finally { if (current()) { request.current = null; setBusy('') } }
  }
  function confirm() {
    if (checked.current?.selection === selection.current && !request.current && !unknown.current) { setConfirmation(''); setStep(3) }
  }
  async function restore() {
    if (importing.current || unknown.current || request.current || confirmation !== 'RESTORE MY DATA'
      || step !== 3 || checked.current?.selection !== selection.current) return
    importing.current = true
    const selected = selection.current, digest = checked.current.data.sha256
    const owner = lifetime.current, controller = new AbortController()
    request.current = controller; setBusy('restore'); setError(''); setResult(null)
    const current = () => !owner.signal.aborted && !controller.signal.aborted && request.current === controller
    try {
      const data = await endpoints.importArchive(selected.file, selected.scope, digest, { signal: controller.signal })
      if (!validResult(data)) throw new Error(t('个人归档响应格式不正确，请重新校验。'))
      if (current()) { checked.current = null; setPreview(null); setResult(data); setConfirmation(''); setStep(4) }
    } catch (failure) {
      if (current()) {
        // A disconnected POST may already have committed. Never silently replay it.
        unknown.current = true; setUncertain(true); checked.current = null; setPreview(null); setConfirmation('')
        setError(t('个人恢复结果未确认：{0}。请先到资料库、会话或学习页面核实，重复导入可能产生副本。', [failure.message || t('请求失败')]))
      }
    } finally { importing.current = false; if (current()) { request.current = null; setBusy('') } }
  }
  return { file, fileKey, scope, chooseFile, chooseScope, preview, result, confirmation, setConfirmation, error, busy, step,
    uncertain, verify, confirm, restore, reset, back: () => { if (!importing.current && !unknown.current) { setConfirmation(''); setStep(2) } } }
}
