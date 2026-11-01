import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'
import { t } from '../../i18n'

export function useModelSettings() {
  const [form, setForm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [readError, setReadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [probe, setProbe] = useState(null)
  const active = useRef(false)
  const request = useRef(null)

  async function load() {
    if (!active.current || request.current) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setReadError('')
    try {
      const value = await endpoints.modelSettings({ signal: controller.signal })
      if (!value || typeof value.model !== 'string' || typeof value.enabled !== 'boolean' || !['deepseek', 'dashscope', 'openai'].includes(value.provider)) throw new Error(t('模型配置响应格式不正确'))
      if (!controller.signal.aborted) setForm({ ...value, apiKey: '', clearKey: false })
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
    if (request.current) return
    setForm(current => ({ ...current, [key]: value }))
    setProbe(null); setError(''); setNotice('')
  }

  async function run(name) {
    if (!active.current || request.current || !form) return
    const controller = new AbortController()
    request.current = controller
    setBusy(name); setError(''); setNotice(''); setProbe(null)
    try {
      const result = await (name === 'save' ? endpoints.saveModelSettings : endpoints.testModelSettings)(form, { signal: controller.signal })
      if (controller.signal.aborted) return
      if (name === 'save') {
        setForm({ ...result, apiKey: '', clearKey: false })
        setNotice(t('模型配置已保存'))
      } else {
        setProbe(result); setNotice(t('模型连接测试通过，配置尚未保存'))
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message || t('请求失败'))
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy('') }
    }
  }

  return { form, loading, readError, error, notice, busy, probe, load, field, save: () => run('save'), test: () => run('test') }
}
