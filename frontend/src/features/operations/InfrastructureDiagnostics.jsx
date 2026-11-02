import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { t, useI18n } from '../../i18n'
import { useDateFormatter } from '../../hooks/useDateFormatter'

const components = [
  ['mysql', 'MySQL'], ['redis', 'Redis'], ['qdrant', 'Qdrant'],
  ['object_storage', '对象存储'], ['backup_keys', '备份密钥'], ['smtp', 'SMTP 邮件'],
]
const stages = { present: '已配置', missing: '未配置', passed: '通过', failed: '失败',
  not_checked: '未检查', not_run: '未执行', not_required: '无需清理', not_applicable: '不适用' }
const codes = {
  OK: '业务操作及清理已通过', NOT_CONFIGURED: '请先完成服务配置',
  CONNECTION_FAILED: '连接或认证失败', OPERATION_FAILED: '业务操作失败', CLEANUP_FAILED: '清理核验失败，请检查残留诊断资源',
  KEY_CHECK_FAILED: '密钥校验失败', BUSY: '诊断、备份或恢复正在运行，请稍后检查',
  VERIFIED_EMAIL_REQUIRED: '请先验证当前管理员的邮箱', RATE_LIMITED: '请等待一分钟后再次发送',
  SMTP_ACCEPTED: 'SMTP 已接收，请在自己的邮箱确认收信', INVALID_DIAGNOSTIC_RESPONSE: '诊断响应格式不正确',
}
const valid = value => value && ['present', 'missing'].includes(value.configuration)
  && ['connection', 'operation', 'cleanup'].every(key => Object.hasOwn(stages, value[key]))
  && Object.hasOwn(codes, value.code) && typeof value.checked_at === 'string'

export default function InfrastructureDiagnostics({ token }) {
  useI18n()
  const dates = useDateFormatter()
  const [results, setResults] = useState({})
  const requests = useRef(new Map())
  useEffect(() => () => {
    for (const controller of requests.current.values()) controller.abort()
    requests.current.clear()
  }, [])

  async function check(component) {
    if (requests.current.has(component)) return
    const controller = new AbortController()
    requests.current.set(component, controller)
    // A new action replaces previous success; an unknown outcome is never replayed.
    setResults(old => ({ ...old, [component]: { busy: true } }))
    try {
      const data = await api(`/admin/operations/check/${component}`, {
        method: 'POST', signal: controller.signal, headers: { 'X-Admin-Token': token },
      })
      if (!valid(data)) throw new Error('invalid response')
      if (!controller.signal.aborted) setResults(old => ({ ...old, [component]: { data } }))
    } catch {
      if (!controller.signal.aborted) setResults(old => ({ ...old, [component]: { error: true } }))
    } finally {
      if (requests.current.get(component) === controller) requests.current.delete(component)
    }
  }

  return <section className="account-card" aria-labelledby="infrastructure-diagnostics-title">
    <h2 id="infrastructure-diagnostics-title">{t('基础设施业务诊断')}</h2>
    <p className="muted">{t('仅点击时执行隔离的测试读写，完成后核验清理。刷新状态不会触发诊断。备份密钥检查仅验证当前密钥，不会执行备份或恢复。')}</p>
    <p className="muted">{t('测试邮件只发送至当前管理员已验证的邮箱；SMTP 接收不代表邮件已到达收件箱。')}</p>
    <div className="reference-table-wrap"><table className="reference-table"><thead><tr>
      {['服务', '配置', '连接与认证', '业务操作', '清理核验', '结果与时间', '操作'].map(label => <th scope="col" key={label}>{t(label)}</th>)}
    </tr></thead><tbody>{components.map(([key, label]) => {
      const state = results[key] || {}, data = state.data
      return <tr key={key} aria-busy={!!state.busy}><th scope="row">{t(label)}</th>
        {['configuration', 'connection', 'operation', 'cleanup'].map(stage => <td key={stage}>{data ? t(stages[data[stage]]) : '—'}</td>)}
        <td aria-live="polite">{state.busy ? t('正在诊断，请稍候') : state.error
          ? t('未取得诊断结果，操作可能已执行。请确认服务状态后再手动检查。')
          : data ? <>{t(codes[data.code])}<br /><small>{dates.dateTime(data.checked_at)}</small></> : t('尚未检查')}</td>
        <td><button disabled={!!state.busy} onClick={() => check(key)} aria-label={t(key === 'smtp' ? '发送测试邮件' : '检查 {0}', [t(label)])}>
          {t(key === 'smtp' ? '发送测试邮件' : '检查')}
        </button></td>
      </tr>
    })}</tbody></table></div>
  </section>
}
