import { useFormatters } from '../hooks/useFormatters'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BrainCircuit, Plus, Search } from 'lucide-react'
import { endpoints } from '../api/client'
import { DangerZone, FeedbackBlock, Modal, PageHeader, StatusPill } from '../components/ui'

import { DetailPane, MetricCards } from '../components/ReferenceUI'

const categories = { preference: '学习偏好', weak_point: '薄弱知识', progress: '学习进度' }
const states = { active: '学习中', mastered: '已掌握', reinforce: '需巩固', archived: '已归档', ignored: '已忽略' }
function tags(value) { try { return Array.isArray(value) ? value : JSON.parse(value || '[]') } catch { return [] } }
export default function MemoryPage() {
  const dates = useDateFormatter()
  const fmt = useFormatters()
  useI18n();
  const [items, setItems] = useState([])
  const [pending, setPending] = useState([])
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState(new URLSearchParams(window.location.search).get('search') || '')
  const [tagText, setTagText] = useState('')
  const mounted = useRef(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ category: 'preference', content: '', topic: '' })
  const [versions, setVersions] = useState([])
  const lock = useRef(false)
  const detailVersion = useRef(0)
  async function load() {
    const results = await Promise.allSettled([endpoints.managedMemories(), endpoints.pendingMemories()])
    if (!mounted.current) return
    if (results[0].status === 'fulfilled') setItems(results[0].value?.memories || [])
    if (results[1].status === 'fulfilled') setPending(results[1].value || [])
    setLoaded(true)
    setError(results.filter(r => r.status === 'rejected').map(r => r.reason.message).join(' · '))
  }
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false } }, [])
  async function run(action) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e.message); throw e } finally { lock.current = false; setBusy(false) }
  }
  function act(action) { void run(action).catch(() => {}) }
  async function choose(item) {
    const version = ++detailVersion.current
    setSelected({ ...item }); setTagText(tags(item.tags).join(', ')); setVersions([])
    try { const data = await endpoints.memoryVersions(item.id); if (mounted.current && version === detailVersion.current) setVersions(data.versions || []) }
    catch (e) { if (mounted.current && version === detailVersion.current) setError(e.message) }
  }
  async function update(body) {
    const result = await endpoints.updateManagedMemory(selected.id, body)
    const list = result.memories || []
    setItems(list); setSelected(list.find(item => item.id === selected.id) || null); setNotice(t("记忆已保存，检索缓存已更新"))
    try { const history = await endpoints.memoryVersions(selected.id); if (mounted.current) setVersions(history.versions || []) } catch { setNotice(t("记忆已保存，但版本列表未能刷新，请重新打开详情。")) }
  }
  const visible = items.filter(item => (filter === 'all' || (filter === 'confirmed' ? item.confirmed : (item.status || 'active') === filter)) && `${item.content} ${item.topic} ${tags(item.tags).join(' ')}`.toLowerCase().includes(search.toLowerCase()))
  return <div className="standard-page reference-page reference-memory"><PageHeader eyebrow={t("由你决定记住什么")} title={t("学习记忆")} description={t("查看来源、修正推断，管理用于后续学习的个人记忆。")}><button className="primary-button" onClick={() => setOpen(true)}><Plus size={17} />{t("添加记忆")}</button></PageHeader>
    <FeedbackBlock error={error} message={notice} onRetry={error ? load : undefined} />
    <MetricCards items={[{label:t('总记忆数'),value:items.length,icon:BrainCircuit},{label:t('待确认'),value:pending.length},{label:t('已掌握'),value:items.filter(item=>item.status==='mastered').length},{label:t('需巩固'),value:items.filter(item=>item.status==='reinforce').length}]} />
    <div className="reference-split memory-split"><section className="memory-list-panel">
    <div className="memory-filter-tabs" aria-label={t('记忆状态')}>{[['all','全部'],['pending','待确认'],['mastered','已掌握'],['reinforce','需巩固']].map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{t(label)}</button>)}</div>
    <div className="page-toolbar"><label className="search-field"><Search size={17} /><input aria-label={t("搜索记忆")} placeholder={t("搜索内容、主题或标签")} value={search} onChange={e => setSearch(e.target.value)} /></label><label>{t("记忆状态")}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("全部记忆")}</option><option value="pending">{t("待确认")}</option><option value="confirmed">{t("用户已确认")}</option>{Object.entries(states).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><span className="muted">{items.length}{t(" 条记忆 · ")}{pending.length}{t(" 条待确认")}</span></div>
    {['all', 'pending'].includes(filter) && pending.length > 0 && <section className="pending-section"><h2>{t("等待你的确认")}</h2><p className="muted">{t("以下是模型推断，确认前不会作为已确认记忆使用。")}</p><ul className="record-list">{pending.filter(item => `${item.content} ${item.topic}`.includes(search)).map(item => <li key={item.memoryId}><div><StatusPill tone="warning">{t("待确认 · 模型推断")}</StatusPill><h3>{item.topic || t(categories[item.category])}</h3><p>{item.content}</p><small>{t("系统估计置信度：")}{item.confidence == null ? t("无数据") : fmt.percent(item.confidence, 0)}{t("，不代表事实保证。")}</small>{item.sessionId && <Link className="text-link" to={`/chat?session=${item.sessionId}`}>{t("查看来源对话 →")}</Link>}</div><div className="action-row"><button disabled={busy} onClick={() => act(async () => { await endpoints.confirmMemory({ temp_id: item.memoryId, action: 'confirm' }); await load() })}>{t("确认记住")}</button><button disabled={busy} onClick={() => act(async () => { await endpoints.confirmMemory({ temp_id: item.memoryId, action: 'dismiss' }); await load() })}>{t("忽略")}</button></div></li>)}</ul></section>}
    {filter !== 'pending' && <div className="reference-table-wrap" role="region" tabIndex={0} aria-label={t('记忆列表')}><table className="reference-table"><thead><tr>{['记忆标题','来源','标签','置信度','最后更新','学习状态'].map(label=><th scope="col" key={label}>{t(label)}</th>)}</tr></thead><tbody>{visible.map(item=><tr key={item.id} className={selected?.id===item.id?'is-selected':''}><td><button onClick={()=>choose(item)}><span className="record-title"><BrainCircuit size={17}/>{item.topic || t(categories[item.category]) || t('学习记忆')}</span><small className="line-clamp">{item.content}</small></button></td><td>{item.source_session_id?<Link to={`/chat?session=${item.source_session_id}`}>{t('来源对话')}</Link>:t('手动记忆')}<small>{item.confirmed?t('用户已确认'):t('待核验')}</small></td><td>{tags(item.tags).map(tag=><span className="quiet-tag" key={tag}>{tag}</span>)}</td><td>{item.confidence==null?'—':fmt.percent(item.confidence, 0)}{item.confidence!=null&&<div className="confidence-bar"><span style={{width:`${Math.max(0,Math.min(100,item.confidence*100))}%`}}/></div>}</td><td>{item.updated_at?dates.date(item.updated_at):'—'}</td><td><StatusPill tone={item.status==='mastered'?'success':item.status==='reinforce'?'warning':'neutral'}>{t(states[item.status||'active'])}</StatusPill></td></tr>)}</tbody></table></div>}
    {loaded && (filter === 'pending' ? !pending.filter(item => `${item.content} ${item.topic}`.includes(search)).length : !visible.length && !(filter === 'all' && pending.some(item => `${item.content} ${item.topic}`.includes(search)))) && <div className="empty-state"><BrainCircuit size={34} /><h2>{t("暂无符合条件的记忆")}</h2><p>{t("可以手动补充学习偏好，也可以在对话后确认系统建议。")}</p></div>}{!loaded && <p role="status">{t("正在读取记忆…")}</p>}
    </section><DetailPane open={!!selected} title={t("记忆详情")} onClose={() => { detailVersion.current++; setSelected(null) }} busy={busy}>{selected && <><FeedbackBlock error={error} message={notice} /><p>{t("保存原因：")}{selected.confirmed ? t("用户已确认") : t("根据学习记录提取，尚未标记为用户确认")}。</p><p>{t("置信度：")}{selected.confidence == null ? t("未提供估计值") : t("{0}（系统估计）", [fmt.percent(selected.confidence, 0)])}</p>{selected.source_session_id ? <Link className="text-link" to={`/chat?session=${selected.source_session_id}`}>{t("返回来源对话 →")}</Link> : <p className="muted">{t("此记录未提供来源链接。")}</p>}
      <form className="form-stack" onSubmit={e => { e.preventDefault(); act(() => update({ content: selected.content, topic: selected.topic, tags: tagText.split(/[,，]/).map(s => s.trim()).filter(Boolean) })) }}><label>{t("主题")}<input maxLength={200} value={selected.topic || ''} onChange={e => setSelected({ ...selected, topic: e.target.value })} /></label><label>{t("内容")}<textarea required rows={6} maxLength={10000} value={selected.content} onChange={e => setSelected({ ...selected, content: e.target.value })} /></label><label>{t("标签（以逗号分隔）")}<input maxLength={1000} value={tagText} onChange={e => setTagText(e.target.value)} /></label><button className="primary-button" disabled={busy}>{t("保存修改")}</button></form>
      <div className="action-row">{!selected.confirmed && <button disabled={busy} onClick={() => act(() => update({ confirmed: true }))}>{t("确认记忆")}</button>}<label>{t("学习状态")}<select disabled={busy} value={selected.status || 'active'} onChange={e => act(() => update({ status: e.target.value }))}>{Object.entries(states).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><Link className="text-link" to="/review">{t("安排复习 →")}</Link></div><p className="muted">{t("归档或忽略后不再参与记忆检索；原记录保留，可随时恢复为学习中。")}</p>
      <details><summary>{t("历史版本（")}{versions.length}）</summary><ul className="plain-list">{versions.map(version => <li key={version.version}><p>{t("版本 ")}{version.version} · {version.reason || version.action}</p><p>{version.content}</p><button disabled={busy} onClick={() => act(async () => { const data = await endpoints.restoreMemory(selected.id, version.version); setItems(data.memories || []); setSelected((data.memories || []).find(item => item.id === selected.id)); setVersions((await endpoints.memoryVersions(selected.id)).versions || []); setNotice(t("历史版本已恢复")) })}>{t("恢复此版本")}</button></li>)}</ul></details>
      <DangerZone title={t("删除此记忆")} description={t("从记忆检索中移除此条目并清除缓存。版本历史仍按保留策略保存，可用于恢复。")} action={t("删除记忆")} confirmText="DELETE MEMORY" busy={busy} onConfirm={() => run(async () => { const data = await endpoints.deleteManagedMemory(selected.id); setItems(data.memories || []); setSelected(null); setNotice(t("记忆已删除")) })} />
    </>}</DetailPane></div>
    <Modal open={open} title={t("添加学习记忆")} busy={busy} onClose={() => setOpen(false)}><form className="form-stack" onSubmit={e => { e.preventDefault(); act(async () => { await endpoints.writeMemory(form); setOpen(false); setForm({ category: 'preference', content: '', topic: '' }); await load() }) }}><FeedbackBlock error={error} /><label>{t("类型")}<select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>{Object.entries(categories).map(([value, text]) => <option key={value} value={value}>{t(text)}</option>)}</select></label><label>{t("主题")}<input maxLength={200} value={form.topic} onChange={e => setForm({ ...form, topic: e.target.value })} /></label><label>{t("内容")}<textarea required maxLength={10000} rows={5} value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} /></label><button disabled={busy} className="primary-button">{t("保存记忆")}</button></form></Modal>
  </div>
}
import '../styles/reference-pages.css'
