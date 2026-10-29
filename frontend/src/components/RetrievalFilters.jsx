import { t, useI18n } from '../i18n'
import { useEffect, useState } from 'react'
import { endpoints } from '../api/client'
import '../styles/retrieval-filters.css'

export const emptyFilters = { selected_document_ids: [], tags: [], date_from: '', date_to: '' }

export default function RetrievalFilters({ kbIds, value, onChange }) {
  useI18n();
  const [documents, setDocuments] = useState([])
  const [error, setError] = useState('')
  const [tagText, setTagText] = useState(value.tags.join(','))
  const key = JSON.stringify(kbIds)
  const tagsKey = JSON.stringify(value.tags)
  useEffect(() => {
    setTagText(current => JSON.stringify(current.split(/[,，]/).map(tag => tag.trim()).filter(Boolean)) === tagsKey
      ? current : JSON.parse(tagsKey).join(', '))
  }, [tagsKey])
  useEffect(() => {
    let active = true
    Promise.all(JSON.parse(key).map(id => endpoints.documents(id))).then(lists => {
      if (lists.some(list => !Array.isArray(list))) throw new Error(t("文档列表响应异常，请刷新重试"))
      if (active) { setDocuments(lists.flat()); setError('') }
    }).catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [key])
  const update = patch => onChange({ ...value, ...patch })
  const count = value.selected_document_ids.length + value.tags.length + Number(Boolean(value.date_from || value.date_to))
  return <details className="retrieval-filters">
    <summary>{t("检索范围")}{count ? t(" · {0} 项筛选", [count]) : ''}</summary>
    <div className="retrieval-filter-fields">
      {error && <p role="alert">{error}</p>}
      <label>{t("指定文档（可多选）")}<select multiple value={value.selected_document_ids}
        onChange={event => update({ selected_document_ids: [...event.target.selectedOptions].map(option => option.value) })}>
        {documents.filter(doc => ['ready', 'partial'].includes(doc.status)).map(doc => <option key={doc.id} value={String(doc.id)}>{doc.fileName || doc.file_name}</option>)}
      </select></label>
      <label>{t("标签（逗号分隔，同时满足）")}<input value={tagText} placeholder={t("例如：课程,重点")}
        onChange={event => { setTagText(event.target.value); update({ tags: event.target.value.split(/[,，]/).filter(tag => tag.trim()).map(tag => tag.trim()) }) }} /></label>
      <label>{t("导入起始日期")}<input type="date" value={value.date_from} onChange={event => update({ date_from: event.target.value })} /></label>
      <label>{t("导入结束日期")}<input type="date" value={value.date_to} min={value.date_from} onChange={event => update({ date_to: event.target.value })} /></label>
      <button type="button" onClick={() => { setTagText(''); onChange({ ...emptyFilters }) }}>{t("清除筛选")}</button>
    </div>
  </details>
}
