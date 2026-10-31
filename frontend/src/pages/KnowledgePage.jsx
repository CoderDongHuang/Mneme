import { useDateFormatter } from '../hooks/useDateFormatter'
import { useFormatters } from '../hooks/useFormatters'
import { t, useI18n } from '../i18n'
import {
  ArrowUpRight,
  BookCopy,
  File,
  FileArchive,
  FileChartColumn,
  FileSpreadsheet,
  FileText,
  History,
  Plus,
  Search,
  Trash2,
  RefreshCw,
  UploadCloud,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { endpoints, openNotificationStream } from "../api/client";
import DocumentDetail from "../components/DocumentDetail";
import { Modal, DangerZone, FeedbackBlock } from "../components/ui";
import { usePreferences } from "../state/PreferencesContext";
import LoadingState from "../components/LoadingState";
import StatusBadge from "../components/StatusBadge";
import useUploadQueue from "../hooks/useUploadQueue";
import { useAuth } from "../state/AuthContext";
import "../styles/knowledge.css";
import '../styles/reference-knowledge.css'

function ParseReport({ value }) {
  useI18n();
  const dates = useDateFormatter();
  let report;
  try { report = JSON.parse(value); } catch { return <small>{t("解析报告格式无效，请重新解析")}</small>; }
  const reasons = { no_text: t("未提取到文本（可能为空白页或扫描件）"), ocr_unavailable: t("OCR 不可用"), low_ocr_confidence: t("OCR 置信度偏低，请核对原文"), table_parser_unavailable: t("表格解析器不可用"), table_parse_failed: t("表格解析失败"), vision_parse_failed: t("图片理解失败") };
  return <div className="parse-report">
    <small>{t("解析器：")}{report.parser_version || t("未知")}{t(" · 索引时间：")}{report.indexed_at ? dates.dateTime(report.indexed_at) : t("未知")}</small>
    <small>{t("文件 SHA-256：")}{report.content_sha256 || t("未知")}</small>
    {(report.warnings || []).map((warning, index) => <small key={index}>
      {warning.page > 0 ? t("第 {0} 页：", [warning.page]) : t("文件：")}{reasons[warning.code] || warning.code}
    </small>)}
    {!(report.warnings || []).length && <small>{t("已启用的解析步骤未报告异常；仍建议抽查原文。")}</small>}
  </div>;
}

function fileIcon(name = "") {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["xlsx", "xlsm", "csv"].includes(extension)) return FileSpreadsheet;
  if (extension === "pptx") return FileChartColumn;
  if (extension === "pdf") return FileArchive;
  if (["md", "markdown", "txt", "html", "htm"].includes(extension)) return FileText;
  return File;
}

export default function KnowledgePage() {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n();
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [activeKbId, setActiveKbId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const { session } = useAuth();
  const activeKbRef = useRef(null);
  const actionLock = useRef(false);
  const [baseBusy, setBaseBusy] = useState(false);
  const { queue: uploadQueue, uploading, upload: submitFiles, retry, cancel } = useUploadQueue(`mneme.uploadQueue.${session?.userId || session?.username}`, (kbId, document) => {
    if (activeKbRef.current === kbId) setDocuments(current => [document, ...current.filter(item => item.id !== document.id)]);
  });
  const { preferences } = usePreferences();
  const [fileType, setFileType] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedIds, setSelectedIds] = useState([]);
  const [detail, setDetail] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const bulkLock = useRef(false);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState("");
  const [notifications, setNotifications] = useState([]);
  const fileRef = useRef(null);
  const replaceRef = useRef(null);
  const [replacingDocument, setReplacingDocument] = useState(null);
  const [versionDialog, setVersionDialog] = useState(null);
  const documentLocks = useRef(new Set());
  const [documentBusy, setDocumentBusy] = useState({});
  const versionRequest = useRef(0);

  async function withDocument(document, action) {
    if (documentLocks.current.has(document.id)) return;
    documentLocks.current.add(document.id);
    setDocumentBusy(current => ({ ...current, [document.id]: true }));
    try { await action(); }
    catch (requestError) { setError(requestError.message); }
    finally {
      documentLocks.current.delete(document.id);
      setDocumentBusy(current => ({ ...current, [document.id]: false }));
    }
  }

  const selectKb = useCallback((id) => { activeKbRef.current = id; setActiveKbId(id); setDocuments([]); setSelectedIds([]); setDetail(null); }, []);

  const activeKb = knowledgeBases.find((item) => item.id === activeKbId);

  const loadBases = useCallback(async () => {
    const items = await endpoints.knowledgeBases();
    setKnowledgeBases(items || []);
    selectKb(items?.some(item => item.id === activeKbRef.current) ? activeKbRef.current : items?.[0]?.id || null);
  }, [selectKb]);

  useEffect(() => {
    loadBases()
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false));
  }, [loadBases]);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let refreshAgain = false;
    let timer;
    async function refresh() {
      if (!active || !activeKbId) return;
      if (inFlight) { refreshAgain = true; return; }
      inFlight = true;
      window.clearTimeout(timer);
      try {
        const items = await endpoints.documents(activeKbId);
        if (active && activeKbRef.current === activeKbId) setDocuments(items || []);
      } catch (requestError) { if (active) setError(requestError.message); }
      finally {
        inFlight = false;
        if (active) {
          const delay = refreshAgain ? 0 : 2500;
          refreshAgain = false;
          timer = window.setTimeout(refresh, delay);
        }
      }
    }
    refresh();
    endpoints.notifications().then((items) => {
      if (active) setNotifications(items || []);
    }).catch(() => {});
    const stream = openNotificationStream((item) => {
      if (!active || !item) return;
      setNotifications((current) => [item, ...current.filter((entry) => entry.task_id !== item.task_id)].slice(0, 30));
      if (["completed", "failed", "cancelled"].includes(item.status)) refresh();
    });
    return () => { active = false; window.clearTimeout(timer); stream.close(); };
  }, [activeKbId]);

  async function createBase(event) {
    event.preventDefault();
    if (actionLock.current) return;
    actionLock.current = true;
    setBaseBusy(true);
    setError("");
    try {
      const created = await endpoints.createKnowledgeBase(form);
      setKnowledgeBases(current => [created, ...current]);
      selectKb(created.id);
      setForm({ name: "", description: "" });
      setDialogOpen(false);
    } catch (requestError) { setError(requestError.message); }
    finally { actionLock.current = false; setBaseBusy(false); }
  }

  async function upload(files) {
    await submitFiles(files, activeKbId);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function deleteBase() {
    if (actionLock.current || uploading || !activeKbId || !window.confirm(t("删除“{0}”及其文档、文件和检索索引？服务端失败时可在任务中心重试。", [activeKb?.name]))) return;
    const id = activeKbId;
    actionLock.current = true;
    setBaseBusy(true);
    setError("");
    try {
      await endpoints.deleteKnowledgeBase(id);
      const remaining = knowledgeBases.filter(item => item.id !== id);
      setKnowledgeBases(remaining);
      if (activeKbRef.current === id) selectKb(remaining[0]?.id || null);
    } catch (requestError) { setError(requestError.message); }
    finally { actionLock.current = false; setBaseBusy(false); }
  }

  async function deleteDocument(document) {
    if (!window.confirm(t("删除“{0}”及其检索片段？", [document.fileName]))) return;
    await withDocument(document, async () => {
      setError("");
      await endpoints.deleteDocument(document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "deleting" } : item));
    });
  }

  async function reparseDocument(document) {
    await withDocument(document, async () => {
      setError("");
      await endpoints.reparseDocument(document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "parsing", errorMessage: null, chunkCount: 0 } : item));
    });
  }

  async function repairIndex(document) {
    await withDocument(document, async () => {
      setError('');
      await endpoints.repairDocumentIndex(document.id);
      setDocuments(current => current.map(item => item.id === document.id ? { ...item, status: 'index_repairing' } : item));
      setNotice(t('修复任务已提交，查看任务中心'));
    });
  }

  async function replaceDocument(file) {
    if (!file || !replacingDocument) return;
    await withDocument(replacingDocument, async () => {
      setError("");
      const updated = await endpoints.replaceDocument(replacingDocument.id, file);
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
    });
      setReplacingDocument(null);
      if (replaceRef.current) replaceRef.current.value = "";
  }

  async function showVersions(document) {
    const request = ++versionRequest.current;
    try {
      setVersionDialog({ document, versions: null });
      const versions = await endpoints.documentVersions(document.id);
      if (request === versionRequest.current) setVersionDialog(current => current?.document.id === document.id ? { document, versions: versions || [] } : current);
    } catch (requestError) {
      if (request === versionRequest.current) { setVersionDialog(null); setError(requestError.message); }
    }
  }

  async function restoreVersion(version) {
    if (!versionDialog || !window.confirm(t("恢复到 v{0} 并重新建立索引？", [version.version_number]))) return;
    await withDocument(versionDialog.document, async () => {
      const updated = await endpoints.restoreDocumentVersion(versionDialog.document.id, version.version_number);
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
      setVersionDialog(null);
    });
  }

  const visibleDocuments = useMemo(() => documents.filter(item =>
    item.fileName.toLowerCase().includes(query.toLowerCase()) &&
    (fileType === 'all' || item.fileName.split('.').at(-1).toLowerCase() === fileType) &&
    (statusFilter === 'all' || item.status === statusFilter)), [documents, query, fileType, statusFilter]);
  async function bulk(action) {
    if (bulkLock.current) return;
    bulkLock.current = true; setBulkBusy(true); setError('');
    const selected = documents.filter(item => selectedIds.includes(item.id) && !['deleting', 'parsing', 'index_repairing'].includes(item.status));
    const failures = []; let accepted = 0;
    try {
      for (const document of selected) {
        if (documentLocks.current.has(document.id)) { failures.push(t("{0}: 正在执行其他操作", [document.fileName])); continue; }
        documentLocks.current.add(document.id);
        try {
          await (action === 'delete' ? endpoints.deleteDocument(document.id) : endpoints.reparseDocument(document.id));
          accepted++;
          setSelectedIds(ids => ids.filter(id => id !== document.id));
          setDocuments(items => items.map(item => item.id === document.id ? { ...item, status: action === 'delete' ? 'deleting' : 'parsing' } : item));
        } catch (e) { failures.push(`${document.fileName}: ${e.message}`); }
        finally { documentLocks.current.delete(document.id); }
      }
      setNotice(t("已提交 {0} 项，失败 {1} 项。失败项保留选中，可重试。", [fmt.integer(accepted), fmt.integer(failures.length)]));
      if (failures.length) setError(failures.join(' · '));
    } finally { bulkLock.current = false; setBulkBusy(false); }
  }
  const readyCount = documents.filter((item) => ['ready', 'partial', 'index_pending', 'index_repairing'].includes(item.status)).length;
  const chunkCount = documents.reduce(
    (sum, item) => sum + (item.chunkCount || 0),
    0,
  );

  const previewDocument = detail === false ? null : documents.find(item => item.id === detail?.id) || (window.innerWidth >= 1280 ? visibleDocuments[0] : null);
  return (
    <div className="knowledge-page reference-knowledge">
      <header className="knowledge-masthead"><div><h1>{t('知识库')}</h1><p>{t('管理资料、查看解析质量、追踪索引状态')}</p></div></header>
      <input ref={replaceRef} type="file" hidden accept=".pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.md,.markdown,.txt,.html,.htm" onChange={event => replaceDocument(event.target.files?.[0])} />
      <input ref={fileRef} type="file" multiple hidden accept=".pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.md,.markdown,.txt,.html,.htm" onChange={event => upload(event.target.files)} />
      <div className="reference-split knowledge-split">
        <section className="knowledge-files" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (activeKbId) upload(event.dataTransfer.files) }}>
          <div className="knowledge-controls">
            <label className="search-field"><Search size={18} /><input aria-label={t('筛选文档')} value={query} onChange={e => setQuery(e.target.value)} placeholder={t('搜索文件名、关键词…')} /></label>
            <select aria-label={t('文件类型')} value={fileType} onChange={e => setFileType(e.target.value)}><option value="all">{t('文件类型')}</option>{[...new Set(documents.map(item => item.fileName.split('.').at(-1).toLowerCase()))].map(type => <option key={type}>{type}</option>)}</select>
            <select aria-label={t('处理状态')} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="all">{t('全部状态')}</option>{[...new Set(documents.map(item => item.status))].map(status => <option key={status}>{status}</option>)}</select>
            <button className="primary-button" disabled={uploading || !activeKbId} onClick={() => fileRef.current?.click()}><UploadCloud size={17} />{uploading ? t('处理中') : t('导入资料')}</button>
          </div>
          <div className="knowledge-library-bar"><select aria-label={t('资料库')} value={activeKbId || ''} onChange={e => selectKb(knowledgeBases.find(kb => String(kb.id) === e.target.value)?.id || null)}>{!knowledgeBases.length && <option value="">{t('还没有资料库')}</option>}{knowledgeBases.map(kb => <option value={kb.id} key={kb.id}>{kb.name}</option>)}</select><button onClick={() => setDialogOpen(true)}><Plus size={15} />{t('新建资料库')}</button>{activeKb && <button className="icon-button" aria-label={t('删除资料库')} disabled={baseBusy || uploading} onClick={deleteBase}><Trash2 size={15} /></button>}<span>{fmt.integer(documents.length)} {t('文档')} · {fmt.integer(readyCount)} {t('可检索')} · {fmt.integer(chunkCount)} {t('语义片段')}</span></div>
          <FeedbackBlock error={error} message={notice} />
          {loading ? <LoadingState /> : !activeKb ? <div className="documents-empty"><BookCopy size={32} /><h2>{t('建立第一个资料库')}</h2><p>{t('不同课程或主题建议分别管理。')}</p><button onClick={() => setDialogOpen(true)}>{t('新建资料库')}</button></div> : <>
            <div className="document-table">
              <div className="document-row document-header"><span>{t('文件信息')}</span><span>{t('语义片段')}</span><span>{t('最后更新')}</span><span>{t('索引状态')}</span><span /></div>
              {visibleDocuments.map(document => { const Icon = fileIcon(document.fileName); return <div className={`document-row ${previewDocument?.id === document.id ? 'is-selected' : ''}`} key={document.id}>
                <div className="document-name"><input type="checkbox" aria-label={t('选择 {0}', [document.fileName])} disabled={bulkBusy || ['deleting', 'parsing', 'index_repairing'].includes(document.status)} checked={selectedIds.includes(document.id)} onChange={e => setSelectedIds(ids => e.target.checked ? [...ids, document.id] : ids.filter(id => id !== document.id))} /><span className={`file-icon file-${document.fileName.split('.').at(-1).toLowerCase()}`}><Icon size={26} /><small>{document.fileName.split('.').at(-1).toUpperCase()}</small></span><div><button className="document-title" onClick={() => setDetail(document)}>{document.fileName}</button><small>{document.errorMessage || t('文档编号 {0}', [document.id])}</small></div></div>
                <span>{document.chunkCount || 0}</span><time>{document.updatedAt ? dates.date(document.updatedAt) : '—'}</time><StatusBadge status={document.status} />
                <details className="row-actions"><summary aria-label={t('文档操作：{0}', [document.fileName])}>···</summary><div>{!['deleting', 'parsing', 'index_repairing'].includes(document.status) && <><button disabled={documentBusy[document.id]} onClick={() => showVersions(document)}><History size={15} />{t('版本历史')}</button><button disabled={documentBusy[document.id]} onClick={() => { setReplacingDocument(document); replaceRef.current?.click() }}><RefreshCw size={15} />{t('替换文件')}</button><button disabled={documentBusy[document.id]} onClick={() => reparseDocument(document)}><ArrowUpRight size={15} />{t('重新解析')}</button><button disabled={documentBusy[document.id]} onClick={() => deleteDocument(document)}><Trash2 size={15} />{t('删除文档')}</button></>}{document.parseReport && <details><summary>{t('解析报告')}</summary><ParseReport value={document.parseReport} /></details>}</div></details>
              </div> })}
              {!visibleDocuments.length && <div className="documents-empty"><BookCopy size={30} /><strong>{t('这里还没有资料')}</strong><span>{t('可将文件拖入列表，或点击导入资料。')}</span></div>}
            </div>
            <details className="bulk-tools"><summary>{t('批量操作')} · {fmt.integer(selectedIds.length)} {t('已选择')}</summary><div className="action-row"><button disabled={bulkBusy} onClick={() => setSelectedIds(visibleDocuments.filter(item => !['deleting','parsing','index_repairing'].includes(item.status)).map(item => item.id))}>{t('选择筛选结果')}</button><button disabled={bulkBusy || !selectedIds.length} onClick={() => bulk('reparse')}>{t('重新解析所选 (')}{fmt.integer(selectedIds.length)})</button></div>{selectedIds.length > 0 && <DangerZone title={t('批量删除所选文档')} description={t('删除 {0} 个所选文档及其索引。失败项保留以便重试。', [fmt.integer(selectedIds.length)])} action={t('删除所选')} confirmText="DELETE DOCUMENTS" busy={bulkBusy} onConfirm={() => bulk('delete')} />}</details>
          </>}
          {uploadQueue.length > 0 && <div className="upload-queue" aria-live="polite">{uploadQueue.map(item => <div className={`upload-queue-item ${item.status}`} key={item.id}><strong>{item.name}</strong><span>{t(item.message)}</span>{item.status === 'failed' && <button disabled={uploading} onClick={() => retry(item)}>{t('重试此文件')}</button>}{['pending', 'uploading', 'uncertain'].includes(item.status) && <button onClick={() => cancel(item)}>{t(item.status === 'uncertain' ? '核实上传状态' : '取消上传')}</button>}{item.status === 'submitted' && <a href="/tasks">{t('任务中心')}</a>}</div>)}</div>}
          <section className="recent-activity"><header><h3>{t('最近活动')}</h3><a href="/tasks">{t('查看全部 →')}</a></header>{preferences.notifications && notifications.length ? notifications.slice(0, 5).map(item => <div key={item.task_id}><StatusBadge status={item.status} /><span>{item.file_name || (item.task_type === 'document_ingest' ? t('文档解析') : t('资料库任务'))}</span><small>{item.error_message || (item.status === 'completed' ? t('已完成') : t('处理中'))}</small></div>) : <p className="muted">{t('暂无处理活动')}</p>}</section>
        </section>
        <DocumentDetail document={previewDocument} onClose={() => setDetail(false)} onRepairIndex={repairIndex} indexBusy={documentBusy[previewDocument?.id]} />
      </div>

      <Modal open={dialogOpen} title={t("新建资料库")} busy={baseBusy} onClose={() => setDialogOpen(false)}>
          <form
            className="kb-dialog"
            onSubmit={createBase}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>{t("新资料库")}</span>
                <h2>{t("新建资料库")}</h2>
              </div>
              <button type="button" onClick={() => setDialogOpen(false)}>
                <X size={18} />
              </button>
            </header>
            <label>
              <span>{t("名称")}</span>
              <input
                autoFocus
                required
                maxLength={100}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder={t("例如：机器学习基础")}
              />
            </label>
            <label>
              <span>{t("说明")}</span>
              <textarea
                rows={4}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
                placeholder={t("记录资料范围与学习目标")}
              />
            </label>
            {error && <p role="alert" className="page-error">{error}</p>}
            <button className="dialog-submit" disabled={baseBusy}>
              {baseBusy ? t("正在创建…") : t("创建资料库")}
              <ArrowUpRight size={17} />
            </button>
          </form>
      </Modal>
      {versionDialog && (
        <Modal title={t("版本历史")} onClose={() => { versionRequest.current++; setVersionDialog(null); }}>
          <section className="version-dialog">
            <header>
              <div><span>{t("版本历史")}</span><h2>{versionDialog.document.fileName}</h2></div>
              <button type="button" onClick={() => setVersionDialog(null)}><X size={18} /></button>
            </header>
            <div className="version-list">
              {versionDialog.versions === null && <LoadingState label={t("正在读取版本")} />}
              {versionDialog.versions?.map((version) => (
                <button key={version.version_number} disabled={Boolean(version.active) || documentBusy[versionDialog.document.id]} onClick={() => restoreVersion(version)}>
                  <span>
                    <strong>v{version.version_number} · {version.file_name}</strong>
                    <small>{String(version.sha256).slice(0, 12)} · {dates.dateTime(version.created_at)}</small>
                  </span>
                  <StatusBadge status={version.active ? "active" : "ready"} />
                </button>
              ))}
            </div>
          </section>
        </Modal>
      )}
    </div>
  );
}
