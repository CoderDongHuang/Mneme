import { useDateFormatter } from '../hooks/useDateFormatter'
import { useFormatters } from '../hooks/useFormatters'
import { t, useI18n } from '../i18n'
import {
  ArrowUpRight,
  BookCopy,
  Plus,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { endpoints } from "../api/client";
import useKnowledgeReads from '../features/knowledge/useKnowledgeReads'
import KnowledgeDocumentList from '../features/knowledge/KnowledgeDocumentList'
import DocumentDetail from "../components/DocumentDetail";
import { Modal, FeedbackBlock } from "../components/ui";
import { usePreferences } from "../state/PreferencesContext";
import LoadingState from "../components/LoadingState";
import StatusBadge from "../components/StatusBadge";
import useUploadQueue from "../hooks/useUploadQueue";
import { useAuth } from "../state/AuthContext";
import "../styles/knowledge.css";
import '../styles/reference-knowledge.css'
const empty = [];

export default function KnowledgePage() {
  const { session } = useAuth();
  return <KnowledgeView key={session?.userId || session?.username || 'anonymous'} session={session} />;
}

function KnowledgeView({ session }) {
  const fmt = useFormatters()
  const dates = useDateFormatter()
  useI18n();
  const { bases: baseRead, documents: documentRead, notifications: notificationRead, activeKbId, activeKbRef, selectKb } = useKnowledgeReads();
  const knowledgeBases = baseRead.data || empty, documents = documentRead.data || empty;
  const notifications = (notificationRead.data || []).filter((item, index, items) => items.findIndex(other => other.task_id === item.task_id) === index);
  const setKnowledgeBases = baseRead.commit, setDocuments = documentRead.commit;
  const basesUnavailable = baseRead.loading || !!baseRead.error || !baseRead.data;
  const documentsUnavailable = basesUnavailable || documentRead.loading || !!documentRead.error || !documentRead.data;
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
  const fileRef = useRef(null);
  const replaceRef = useRef(null);
  const [replacingDocument, setReplacingDocument] = useState(null);
  const [versionDialog, setVersionDialog] = useState(null);
  const documentLocks = useRef(new Set());
  const [documentBusy, setDocumentBusy] = useState({});
  const versionRequest = useRef(0);

  async function withDocument(document, action) {
    if (documentsUnavailable || !documents.some(item => item.id === document.id) || documentLocks.current.has(document.id)) return;
    documentLocks.current.add(document.id);
    setDocumentBusy(current => ({ ...current, [document.id]: true }));
    try { await action(); }
    catch (requestError) { setError(requestError.message); }
    finally {
      documentLocks.current.delete(document.id);
      setDocumentBusy(current => ({ ...current, [document.id]: false }));
    }
  }

  useEffect(() => { setSelectedIds([]); setDetail(null); versionRequest.current++; setVersionDialog(null); }, [activeKbId]);

  const activeKb = knowledgeBases.find((item) => item.id === activeKbId);

  async function createBase(event) {
    event.preventDefault();
    if (actionLock.current || basesUnavailable) return;
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
    if (documentsUnavailable || !activeKbId) return;
    await submitFiles(files, activeKbId);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function deleteBase() {
    if (actionLock.current || documentsUnavailable || uploading || !activeKbId || !window.confirm(t("删除“{0}”及其文档、文件和检索索引？服务端失败时可在任务中心重试。", [activeKb?.name]))) return;
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
      setNotice(t('删除任务已提交，最终结果请查看任务中心。'));
    });
  }

  async function reparseDocument(document) {
    await withDocument(document, async () => {
      setError("");
      await endpoints.reparseDocument(document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "parsing", errorMessage: null, chunkCount: 0 } : item));
      setNotice(t('解析任务已提交，最终结果请查看任务中心。'));
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
    if (documentsUnavailable) return;
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
    if (bulkLock.current || documentsUnavailable) return;
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
            <button className="primary-button" disabled={uploading || !activeKbId || documentsUnavailable} onClick={() => fileRef.current?.click()}><UploadCloud size={17} />{uploading ? t('处理中') : t('导入资料')}</button>
          </div>
          <div className="knowledge-library-bar"><select aria-label={t('资料库')} value={activeKbId || ''} onChange={e => selectKb(knowledgeBases.find(kb => String(kb.id) === e.target.value)?.id || null)}>{!knowledgeBases.length && <option value="">{t(baseRead.data ? '还没有资料库' : baseRead.error ? '资料库不可用' : '正在读取资料库…')}</option>}{knowledgeBases.map(kb => <option value={kb.id} key={kb.id}>{kb.name}</option>)}</select><button disabled={basesUnavailable} onClick={() => setDialogOpen(true)}><Plus size={15} />{t('新建资料库')}</button>{activeKb && <button className="icon-button" aria-label={t('删除资料库')} disabled={baseBusy || uploading || documentsUnavailable} onClick={deleteBase}><Trash2 size={15} /></button>}<span>{documentRead.data && <>{fmt.integer(documents.length)} {t('文档')} · {fmt.integer(readyCount)} {t('可检索')} · {fmt.integer(chunkCount)} {t('语义片段')}</>}</span></div>
          <section aria-label={t('资料库读取')} aria-busy={baseRead.loading}><FeedbackBlock error={baseRead.error} onRetry={baseRead.error && !baseRead.loading ? baseRead.refresh : undefined} />{baseRead.data && baseRead.error && <p className="muted">{t('资料库记录可能已过期，刷新成功后可继续操作。')}</p>}</section>
          {activeKb && <section aria-label={t('文档读取')} aria-busy={documentRead.loading}>{documentRead.loading && <p role="status">{t('正在读取文档列表…')}</p>}<FeedbackBlock error={documentRead.error} onRetry={documentRead.error && !documentRead.loading ? documentRead.refresh : undefined} />{documentRead.data && documentRead.error && <p className="muted">{t('文档记录可能已过期，刷新成功后可继续操作。')}</p>}</section>}
          <FeedbackBlock error={error} /><FeedbackBlock message={notice} />
          {baseRead.data === null && baseRead.loading ? <LoadingState /> : baseRead.data === null ? null : !activeKb && !baseRead.error ? <div className="documents-empty"><BookCopy size={32} /><h2>{t('建立第一个资料库')}</h2><p>{t('不同课程或主题建议分别管理。')}</p><button disabled={basesUnavailable} onClick={() => setDialogOpen(true)}>{t('新建资料库')}</button></div> : activeKb ? <>
            <KnowledgeDocumentList
              documents={documents}
              visibleDocuments={visibleDocuments}
              documentRead={documentRead}
              documentsUnavailable={documentsUnavailable}
              bulkBusy={bulkBusy}
              selectedIds={selectedIds}
              setSelectedIds={setSelectedIds}
              previewDocument={previewDocument}
              documentBusy={documentBusy}
              onSelect={setDetail}
              onShowVersions={showVersions}
              onReplace={document => { setReplacingDocument(document); replaceRef.current?.click() }}
              onReparse={reparseDocument}
              onDelete={deleteDocument}
              onBulk={bulk}
            />
          </> : null}
          {uploadQueue.length > 0 && <div className="upload-queue" aria-live="polite">{uploadQueue.map(item => <div className={`upload-queue-item ${item.status}`} key={item.id}><strong>{item.name}</strong><span>{t(item.message)}</span>{item.status === 'failed' && <button disabled={uploading} onClick={() => retry(item)}>{t('重试此文件')}</button>}{['pending', 'uploading', 'uncertain'].includes(item.status) && <button onClick={() => cancel(item)}>{t(item.status === 'uncertain' ? '核实上传状态' : '取消上传')}</button>}{item.status === 'submitted' && <a href="/tasks">{t('任务中心')}</a>}</div>)}</div>}
          <section className="recent-activity" aria-label={t('最近活动')} aria-busy={notificationRead.loading}><header><h3>{t('最近活动')}</h3><a href="/tasks">{t('查看全部 →')}</a></header>{notificationRead.loading && <p role="status">{t('正在读取最近活动…')}</p>}<FeedbackBlock error={notificationRead.error} onRetry={notificationRead.error && !notificationRead.loading ? notificationRead.refresh : undefined} />{preferences.notifications && notifications.length ? notifications.slice(0, 5).map(item => <div key={item.task_id}><StatusBadge status={item.status} /><span>{item.file_name || (item.task_type === 'document_ingest' ? t('文档解析') : t('资料库任务'))}</span><small>{item.error_message || (item.status === 'completed' ? t('已完成') : t('处理中'))}</small></div>) : !notificationRead.loading && !notificationRead.error && <p className="muted">{t(preferences.notifications ? '暂无处理活动' : '应用通知已关闭')}</p>}</section>
        </section>
        <DocumentDetail document={previewDocument} onClose={() => setDetail(false)} onRepairIndex={repairIndex} indexBusy={documentsUnavailable || documentBusy[previewDocument?.id]} />
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
            <button className="dialog-submit" disabled={baseBusy || basesUnavailable}>
              {baseBusy ? t("正在创建…") : t("创建资料库")}
              <ArrowUpRight size={17} />
            </button>
          </form>
      </Modal>
      {versionDialog && (
        <Modal title={t("版本历史")} onClose={() => { versionRequest.current++; setVersionDialog(null); }}>
          <section className="version-dialog">
            <h3>{versionDialog.document.fileName}</h3>
            <div className="version-list">
              {versionDialog.versions === null && <LoadingState label={t("正在读取版本")} />}
              {versionDialog.versions?.map((version) => (
                <button key={version.version_number} disabled={documentsUnavailable || Boolean(version.active) || documentBusy[versionDialog.document.id]} onClick={() => restoreVersion(version)}>
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
