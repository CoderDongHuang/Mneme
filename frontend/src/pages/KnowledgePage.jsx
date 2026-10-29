import { t, useI18n } from '../i18n'
import {
  Archive,
  ArrowUpRight,
  BookCopy,
  File,
  FileArchive,
  FileChartColumn,
  FileSpreadsheet,
  FileText,
  FolderPlus,
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

function ParseReport({ value }) {
  useI18n();
  let report;
  try { report = JSON.parse(value); } catch { return <small>{t("解析报告格式无效，请重新解析")}</small>; }
  const reasons = { no_text: t("未提取到文本（可能为空白页或扫描件）"), ocr_unavailable: t("OCR 不可用"), low_ocr_confidence: t("OCR 置信度偏低，请核对原文"), table_parser_unavailable: t("表格解析器不可用"), table_parse_failed: t("表格解析失败"), vision_parse_failed: t("图片理解失败") };
  return <div className="parse-report">
    <small>{t("解析器：")}{report.parser_version || t("未知")}{t(" · 索引时间：")}{report.indexed_at || t("未知")}</small>
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
    const selected = documents.filter(item => selectedIds.includes(item.id) && !['deleting', 'parsing'].includes(item.status));
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
      setNotice(t("已提交 {0} 项，失败 {1} 项。失败项保留选中，可重试。", [accepted, failures.length]));
      if (failures.length) setError(failures.join(' · '));
    } finally { bulkLock.current = false; setBulkBusy(false); }
  }
  const readyCount = documents.filter((item) => item.status === "ready").length;
  const chunkCount = documents.reduce(
    (sum, item) => sum + (item.chunkCount || 0),
    0,
  );

  return (
    <div className="knowledge-page">
      <header className="knowledge-masthead">
        <div>
          <p className="eyebrow">{t("知识资料管理")}</p>
          <h1>{t("资料库")}</h1>
          <p>{t("把课件、笔记与复杂文档整理成可追溯的检索依据。")}</p>
        </div>
        <button onClick={() => setDialogOpen(true)}>
          <FolderPlus size={18} />{t(" 新建资料库 ")}</button>
      </header>

      <div className="knowledge-layout">
        <input
          ref={replaceRef}
          type="file"
          hidden
          accept=".pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.md,.markdown,.txt,.html,.htm"
          onChange={(event) => replaceDocument(event.target.files?.[0])}
        />
        <aside className="kb-index">
          <div className="kb-index-label">
            <span>{t("资料库")}</span>
            <strong>{knowledgeBases.length.toString().padStart(2, "0")}</strong>
          </div>
          {loading ? (
            <LoadingState />
          ) : knowledgeBases.length ? (
            knowledgeBases.map((kb, index) => (
              <button
                key={kb.id}
                onClick={() => selectKb(kb.id)}
                className={kb.id === activeKbId ? "active" : ""}
              >
                <span className="kb-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>
                  <strong>{kb.name}</strong>
                  <small>{kb.description || t("未填写说明")}</small>
                </span>
                <ArrowUpRight size={17} />
              </button>
            ))
          ) : (
            <div className="kb-empty">
              <Archive size={28} />
              <p>{t("还没有资料库")}</p>
            </div>
          )}
        </aside>

        <main className="document-workbench">
          {activeKb ? (
            <>
              <div className="workbench-head">
                <div>
                  <span>{t("当前资料库")}</span>
                  <h2>{activeKb.name}</h2>
                </div>
                <button
                  className="danger-icon"
                  disabled={baseBusy || uploading}
                  onClick={deleteBase}
                  title={t("删除资料库")}
                >
                  <Trash2 size={18} />
                </button>
              </div>
              <div className="knowledge-metrics">
                <div>
                  <strong>{documents.length}</strong>
                  <span>{t("文档")}</span>
                </div>
                <div>
                  <strong>{readyCount}</strong>
                  <span>{t("可检索")}</span>
                </div>
                <div>
                  <strong>{chunkCount}</strong>
                  <span>{t("语义片段")}</span>
                </div>
              </div>
              <div
                className={`drop-zone ${uploading ? "is-uploading" : ""}`}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  upload(event.dataTransfer.files);
                }}
              >
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  hidden
                  accept=".pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.md,.markdown,.txt,.html,.htm"
                  onChange={(event) => upload(event.target.files)}
                />
                <UploadCloud size={28} />
                <div>
                  <strong>
                    {uploading ? t("正在提交解析任务") : t("拖放文件到这里")}
                  </strong>
                  <span>{t("支持文档、演示文稿、表格、纯文本和网页文件")}</span>
                </div>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? t("处理中") : t("选择文件")}
                </button>
              </div>
              <div className="document-toolbar">
                <div className="document-search">
                  <Search size={17} />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t("筛选文档")}
                  />
                </div>
                <span>{visibleDocuments.length}{t(" 份文档")}</span>
              </div>
              <div className="page-toolbar"><label>{t("文件类型")}<select value={fileType} onChange={e => setFileType(e.target.value)}><option value="all">{t("全部类型")}</option>{[...new Set(documents.map(item => item.fileName.split('.').at(-1).toLowerCase()))].map(type => <option key={type}>{type}</option>)}</select></label><label>{t("处理状态")}<select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="all">{t("全部状态")}</option>{[...new Set(documents.map(item => item.status))].map(status => <option key={status}>{status}</option>)}</select></label><button disabled={bulkBusy} onClick={() => setSelectedIds(visibleDocuments.filter(item => !['deleting','parsing'].includes(item.status)).map(item => item.id))}>{t("选择筛选结果")}</button><button disabled={bulkBusy || !selectedIds.length} onClick={() => bulk('reparse')}>{t("重新解析所选 (")}{selectedIds.length})</button></div>
              {selectedIds.length > 0 && <DangerZone title={t("批量删除所选文档")} description={t("删除 {0} 个所选文档及其索引。失败项保留以便重试。", [selectedIds.length])} action={t("删除所选")} confirmText="DELETE DOCUMENTS" busy={bulkBusy} onConfirm={() => bulk('delete')} />}
              <FeedbackBlock message={notice} />
              {uploadQueue.length > 0 && (
                <div className="upload-queue" aria-live="polite">
                  <p>{t("已提交 ")}{uploadQueue.filter(item => item.status === "submitted").length}{t(" · 失败 ")}{uploadQueue.filter(item => item.status === "failed").length}{t(" · 等待/上传中 ")}{uploadQueue.filter(item => ["pending", "uploading"].includes(item.status)).length}{t(" · 已取消 ")}{uploadQueue.filter(item => item.status === "cancelled").length}</p>
                  {uploadQueue.map((item) => (
                    <div className={`upload-queue-item ${item.status}`} key={item.id}>
                      <strong>{item.name}</strong>
                      <span>{item.message}</span>
                      <small>{t("资料库 ")}{knowledgeBases.find(kb => kb.id === item.kbId)?.name || item.kbId}</small>
                      {item.status === "failed" && <button disabled={uploading} onClick={() => retry(item)}>{t("重试此文件")}</button>}
                      {item.status === "pending" && <button onClick={() => cancel(item)}>{t("取消上传")}</button>}
                    </div>
                  ))}
                </div>
              )}
              {preferences.notifications && notifications.length > 0 && (
                <div className="task-notifications" aria-live="polite">
                  <div><strong>{t("处理通知")}</strong><span>{t("服务端任务状态会在这里更新")}</span></div>
                  {notifications.slice(0, 5).map((item) => (
                    <div className={`task-notification ${item.status}`} key={item.task_id}>
                      <strong>{item.task_type === "document_ingest" ? t("文档解析") : item.task_type === "document_delete" ? t("文档删除") : t("资料库任务")}</strong>
                      <StatusBadge status={item.status} />
                      <span>{item.error_message || (item.status === "completed" ? t("已完成") : item.status === "failed" ? t("处理失败，可在工作台重试") : t("处理中"))}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="document-table">
                <div className="document-row document-header">
                  <span>{t("文件")}</span>
                  <span>{t("状态")}</span>
                  <span>{t("片段")}</span>
                  <span>{t("更新时间")}</span>
                  <span />
                </div>
                {visibleDocuments.map((document) => {
                  const Icon = fileIcon(document.fileName);
                  return (
                    <div className="document-row" key={document.id}>
                      <div className="document-name"><input type="checkbox" aria-label={t("选择 {0}", [document.fileName])} disabled={bulkBusy || ['deleting', 'parsing'].includes(document.status)} checked={selectedIds.includes(document.id)} onChange={e => setSelectedIds(ids => e.target.checked ? [...ids, document.id] : ids.filter(id => id !== document.id))} />
                        <span className="file-icon">
                          <Icon size={19} />
                        </span>
                        <div>
                          <button className="document-title" onClick={() => setDetail(document)}>{document.fileName}</button>
                          <small>
                            {document.errorMessage || t("文档编号 {0}", [document.id])}
                          </small>
                          {document.parseReport && <details>
                            <summary>{t("解析报告")}</summary>
                            <ParseReport value={document.parseReport} />
                          </details>}
                        </div>
                      </div>
                      <span>
                        <StatusBadge status={document.status} />
                      </span>
                      <span>{document.chunkCount || 0}</span>
                      <span>
                        {document.updatedAt
                          ? new Date(document.updatedAt).toLocaleString(
                              "zh-CN",
                              {
                                month: "2-digit",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )
                          : t("刚刚")}
                      </span>
                      <span>
                        {!["deleting", "parsing"].includes(document.status) && <>
                          <button disabled={documentBusy[document.id]} title={t("版本历史")} onClick={() => showVersions(document)}>
                            <History size={16} />
                          </button>
                          <button disabled={documentBusy[document.id]} title={t("替换文件")} onClick={() => { setReplacingDocument(document); replaceRef.current?.click(); }}>
                            <RefreshCw size={16} />
                          </button>
                          <button disabled={documentBusy[document.id]} title={t("重新解析")} onClick={() => reparseDocument(document)}>
                            <ArrowUpRight size={16} />
                          </button>
                          <button disabled={documentBusy[document.id]} title={t("删除文档")} onClick={() => deleteDocument(document)}>
                            <Trash2 size={16} />
                          </button>
                        </>}
                      </span>
                    </div>
                  );
                })}
                {!visibleDocuments.length && (
                  <div className="documents-empty">
                    <BookCopy size={30} />
                    <strong>{t("这里还没有资料")}</strong>
                    <span>{t("上传后可以在对话中选择该资料库进行检索。")}</span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="select-kb-empty">
              <BookCopy size={42} />
              <h2>{t("建立第一个资料库")}</h2>
              <p>{t("不同课程或主题建议分别管理。")}</p>
              <button onClick={() => setDialogOpen(true)}>
                <Plus size={17} />{t(" 新建资料库 ")}</button>
            </div>
          )}
          {error && <div role="alert" className="page-error">{error}</div>}
        </main>
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
      <DocumentDetail document={detail} onClose={() => setDetail(null)} />
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
                    <small>{String(version.sha256).slice(0, 12)} · {new Date(version.created_at).toLocaleString("zh-CN")}</small>
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
