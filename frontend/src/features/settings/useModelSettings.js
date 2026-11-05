import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'
import { t } from '../../i18n'
import { validModelSettings, validPersonalProbe } from './settingsValidation'

const editable = value => ({ ...value, apiKey: '', clearKey: false })
// A transport/server failure can follow a commit. Reconcile with a GET before
// allowing another PUT; never replay a write implicitly.
const rejected = failure => [400, 401, 403, 404, 405, 413, 415, 422, 429].includes(failure.status)

export function useModelSettings() {
  const [form, setForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [readError, setReadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [probe, setProbe] = useState(null)
  const [pending, setPending] = useState(false)
  const [checked, setChecked] = useState(null)
  const active = useRef(false)
  const request = useRef(null)
  const uncertain = useRef(false)

  async function load() {
    if (!active.current || request.current) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setReadError(''); setChecked(null)
    try {
      const value = await endpoints.modelSettings({ signal: controller.signal })
      if (!validModelSettings(value)) throw new Error(t('模型配置响应格式不正确'))
      if (controller.signal.aborted) return
      if (uncertain.current) setChecked(value)
      else setForm(editable(value))
    } catch (failure) {
      if (!controller.signal.aborted) setReadError(failure.message || t('请求失败'))
    } finally {
      if (!controller.signal.aborted) { request.current = null; setLoading(false) }
    }
  }

  useEffect(() => {
    active.current = true
    void load()
    return () => { active.current = false; request.current?.abort(); request.current = null }
  }, [])

  function field(key, value) {
    if (request.current || uncertain.current) return
    setForm(current => ({ ...current, [key]: value }))
    setProbe(null); setError(''); setNotice('')
  }

  function resolve(adopt) {
    if (request.current || !uncertain.current || !checked) return
    setForm(current => adopt ? editable(checked) : { ...current, hasKey: current.provider === checked.provider && !!checked.hasKey, keyMask: current.provider === checked.provider ? checked.keyMask : '' })
    uncertain.current = false
    setPending(false); setChecked(null); setReadError(''); setError('')
  }

  async function run(name) {
    if (!active.current || request.current || uncertain.current || !form) return
    const controller = new AbortController()
    request.current = controller
    setBusy(name); setError(''); setNotice(''); setProbe(null)
    try {
      const result = await (name === 'save' ? endpoints.saveModelSettings : endpoints.testModelSettings)(form, { signal: controller.signal })
      if (controller.signal.aborted) return
      if (name === 'save') {
        if (!validModelSettings(result) || result.provider !== form.provider || result.model !== form.model.trim() || result.enabled !== form.enabled) throw new Error(t('模型配置响应格式不正确'))
        setForm(editable(result))
        setNotice(t('模型配置已保存'))
      } else {
        if (!validPersonalProbe(result)) throw new Error(t('模型测试响应格式不正确，请核实后再试。'))
        setProbe(result); setNotice(t('模型连接测试通过，配置尚未保存'))
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        if (name === 'save' && !rejected(failure)) {
          uncertain.current = true
          setPending(true); setChecked(null)
          setError(t('模型保存结果尚未确认，请先核对服务端配置。'))
        } else setError(failure.message || t('请求失败'))
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy('') }
    }
  }

  return { form, loading, readError, error, notice, busy, probe, pending, checked, load, field, resolve, save: () => run('save'), test: () => run('test') }
}
