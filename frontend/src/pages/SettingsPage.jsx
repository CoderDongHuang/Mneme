import { t, useI18n } from '../i18n'
import { Eye, EyeOff, RefreshCw, Save, Zap } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/client'
import { FeedbackBlock, PageHeader, StatusPill } from '../components/ui'
import { usePreferences } from '../state/PreferencesContext'
import { useModelSettings } from '../features/settings/useModelSettings'

const models = { deepseek: 'deepseek-chat', dashscope: 'qwen-plus', openai: 'gpt-4.1-mini' }
const storageLabels = { backend: '存储方式', object_storage_ready: '文件存储', file_root_exists: '原文件目录', tenant_scoped_paths: '用户数据隔离', traversal_guard: '路径保护', archive_import_guard: '归档导入校验' }
const serviceLabels = { chat: '问答模型', embedding: '文本向量', rerank: '检索重排', ocr: '文字识别' }
const probeLabels = { ok: '连接正常', disabled: '未启用', missing_credentials: '未配置密钥', model_not_loaded: '模型尚未加载', timeout: '连接超时', authentication_failed: '密钥验证失败', quota_or_rate_limit: '额度不足或请求过多', model_unsupported: '模型不可用', runtime_missing: '运行依赖缺失', provider_or_network_error: '服务或网络异常' }
export default function SettingsPage() {
  useI18n();
  const { preferences, save } = usePreferences()
  const [tab, setTab] = useState('model')
  const modelSettings = useModelSettings()
  const { form, field, probe } = modelSettings
  const [health, setHealth] = useState(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [healthError, setHealthError] = useState('')
  const healthRequest = useRef(null)
  const active = useRef(false)
  const [visible, setVisible] = useState(false)
  const [actionBusy, setBusy] = useState('')
  const busy = modelSettings.busy || actionBusy
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [services, setServices] = useState(null)
  async function refreshHealth() {
    if (!active.current || healthRequest.current) return
    const controller = new AbortController()
    healthRequest.current = controller
    setHealthLoading(true); setHealthError('')
    try {
      const value = await endpoints.healthConfig({ signal: controller.signal })
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(t('服务状态响应格式不正确'))
      if (!controller.signal.aborted) setHealth(value)
    } catch (failure) {
      if (!controller.signal.aborted) { setHealth(null); setHealthError(failure.message || t('请求失败')) }
    } finally {
      if (!controller.signal.aborted) { healthRequest.current = null; setHealthLoading(false) }
    }
  }
  useEffect(() => {
    active.current = true
    void refreshHealth()
    return () => { active.current = false; healthRequest.current?.abort(); healthRequest.current = null }
  }, [])
  async function run(name, action, success) {
    if (lock.current || modelSettings.busy) return
    lock.current = true; setBusy(name); setError(''); setNotice('')
    try { const result = await action(); if (active.current) success?.(result) }
    catch (e) { if (active.current) setError(e.message) }
    finally { lock.current = false; if (active.current) setBusy('') }
  }
  return <div className="standard-page reference-page reference-settings">
    <PageHeader eyebrow={t("你的工作空间")} title={t("设置")} description={t("模型、外观和数据管理，各归其位。")} />
    <div className="settings-layout">
      <nav className="section-nav" aria-label={t("设置分组")}>{[['model', t("模型与服务")], ['appearance', t("外观")], ['data', t("数据与隐私")], ['backup', t("备份与恢复")], ['account', t("账户")]].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)} aria-current={tab === id ? 'page' : undefined}>{t(label)}</button>)}</nav>
      <section className="settings-content">
        <FeedbackBlock error={error} message={notice} />
        {tab === 'model' && <><h2>{t("个人模型服务")}</h2><p className="muted">{t("个人模型仅用于你的交互请求。文档解析、向量化和后台任务使用部署方的共享服务。密钥加密保存，不回传明文；测试会实际调用模型，可能产生少量费用。")}</p>
          <FeedbackBlock error={modelSettings.readError && t('模型配置加载失败：{0}', [modelSettings.readError])} onRetry={modelSettings.readError ? modelSettings.load : undefined} />
          <FeedbackBlock error={modelSettings.error} message={modelSettings.notice} />
          {modelSettings.loading && <p role="status">{t('正在读取模型配置…')}</p>}
          {form && <form className="form-stack" aria-label={t('个人模型服务')} aria-busy={!!modelSettings.busy} onSubmit={event => { event.preventDefault(); if (!busy) void modelSettings.save() }}>
            <label>{t("服务商")}<select aria-label={t('服务商')} disabled={!!busy} value={form.provider} onChange={e => { field('provider', e.target.value); field('model', models[e.target.value]); field('apiKey', '') }}><option value="deepseek">DeepSeek</option><option value="dashscope">{t("阿里云百炼 / DashScope")}</option><option value="openai">OpenAI</option></select></label>
            <label>{t("模型名称")}<input disabled={!!busy} required maxLength={120} value={form.model} onChange={e => field('model', e.target.value)} autoComplete="off" /></label>
            <label>{t("API 密钥")}<div className="input-action"><input aria-label={t('API 密钥')} disabled={!!busy} type={visible ? 'text' : 'password'} value={form.apiKey} placeholder={form.hasKey ? t("{0} · 留空保留已存密钥", [form.keyMask]) : t("输入服务商提供的 API 密钥")} maxLength={512} onChange={e => field('apiKey', e.target.value)} autoComplete="new-password" spellCheck="false" /><button type="button" disabled={!!busy} onClick={() => setVisible(!visible)} aria-label={visible ? t("隐藏密钥") : t("显示密钥")}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
            <label className="check-row"><input disabled={!!busy} type="checkbox" checked={form.enabled} onChange={e => field('enabled', e.target.checked)} />{t("为我的请求启用个人模型")}</label>
            <label className="check-row"><input disabled={!!busy} type="checkbox" checked={!!form.clearKey} onChange={e => field('clearKey', e.target.checked)} />{t("保存时清除已存密钥（请先关闭个人模型）")}</label>
            <div className="action-row"><button type="button" disabled={!!busy} onClick={modelSettings.test}><Zap size={16} />{busy === 'test' ? t("测试中…") : t("测试连接")}</button><button className="primary-button" disabled={!!busy}><Save size={16} />{busy === 'save' ? t("保存中…") : t("保存配置")}</button></div>
            {probe && <p role="status"><StatusPill tone="success">{t("实际模型调用通过")}</StatusPill> {probe.model} · {probe.latency_ms} ms</p>}
          </form>}
          <section className="provider-diagnostics" aria-labelledby="provider-diagnostics-title">
            <h3 id="provider-diagnostics-title">{t('共享服务检测')}</h3>
            <p className="muted">{t('检测部署方的问答、向量、重排与文字识别服务，使用合成内容，不读取你的文档。模型调用可能产生少量费用，结果缓存 60 秒。个人模型请使用上方测试连接。')}</p>
            <button disabled={!!busy} onClick={() => { setServices(null); run('providers', endpoints.checkProviders, setServices) }}><Zap size={16} />{busy === 'providers' ? t('检测中…') : t('检测连通性')}</button>
            {services && <div className="provider-results" role="status" aria-label={t('共享服务检测结果')}>{Object.entries(serviceLabels).map(([name, label]) => {
              const result = services.results?.[name]
              return <div key={name}><span>{t(label)}</span><StatusPill tone={result?.state === 'ok' ? 'success' : ['disabled', 'model_not_loaded'].includes(result?.state) ? 'warning' : 'danger'}>{t(probeLabels[result?.state] || '服务状态暂不可用')}</StatusPill>{result && <small className="muted">{result.latency_ms} ms</small>}</div>
            })}{services.cached && <p className="muted">{t('显示最近 60 秒内的检测结果')}</p>}</div>}
          </section>
        </>}
        {tab === 'appearance' && <><h2>{t("外观")}</h2><p className="muted">{t("主题会保存到你的账户，下一次登录自动应用。")}</p><div className="theme-choices">{[['light', t("浅色")], ['dark', t("深色")], ['system', t("跟随系统")]].map(([id, label]) => <button key={id} aria-pressed={preferences.theme === id} onClick={() => run('theme', () => save({ ...preferences, theme: id }), () => setNotice(t("主题已保存")))} disabled={!!busy}>{t(label)}</button>)}</div></>}
        {tab === 'data' && <><h2>{t("数据与隐私")}</h2><p>{t("了解模型调用的数据流，导出个人档案，或管理数据保留。")}</p><div className="link-list"><Link to="/privacy">{t("打开数据与隐私中心 →")}</Link></div></>}
        {tab === 'backup' && <><h2>{t("备份与恢复")}</h2><p>{t("验证个人归档、预览恢复范围和冲突，再确认执行。管理员还可在恢复中心管理整站灾备。")}</p><Link className="text-link" to="/recovery">{t("备份与恢复向导 →")}</Link></>}
        {tab === 'account' && <><h2>{t("账户与安全")}</h2><p>{t("修改资料、语言、时区、通知偏好，查看并撤销登录会话。")}</p><Link className="text-link" to="/profile">{t("管理个人资料 →")}</Link></>}
      </section>
      <aside className="context-panel" aria-label={t('运行状态')}><h3>{t("运行状态")}</h3><FeedbackBlock error={healthError && t('服务状态加载失败：{0}', [healthError])} />{healthLoading ? <p className="muted" role="status">{t('加载中...')}</p> : health ? <><StatusPill tone={health.status === 'unavailable' ? 'danger' : health.demo_mode ? 'warning' : 'success'}>{health.status === 'unavailable' ? t("服务状态暂不可用") : health.demo_mode ? t("离线演示") : t("服务已连接")}</StatusPill><p className="muted">{t("连接状态不代表所有学习流程已通过端到端验证。")}</p><dl>{Object.entries(health.storage || {}).filter(([key]) => storageLabels[key]).map(([key, value]) => <div key={key}><dt>{t(storageLabels[key])}</dt><dd>{typeof value === 'boolean' ? (value ? t("已就绪") : t("未就绪")) : value === 'local' ? t("本地存储") : value === 's3' ? t("对象存储") : String(value)}</dd></div>)}</dl></> : <p className="muted" role="status">{t("服务状态暂不可用")}</p>}<button disabled={healthLoading} onClick={refreshHealth}><RefreshCw size={16} />{t("刷新状态")}</button><p className="muted">{t("Embedding 与 OCR 属于共享索引服务，需由管理员部署与维护。")}</p></aside>
    </div>
  </div>
}
import '../styles/reference-pages.css'
