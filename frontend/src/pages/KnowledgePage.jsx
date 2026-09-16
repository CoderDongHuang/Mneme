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
import { useEffect, useMemo, useRef, useState } from "react";
import { endpoints, openNotificationStream } from "../api/client";
import LoadingState from "../components/LoadingState";
import StatusBadge from "../components/StatusBadge";
import "../styles/knowledge.css";

function fileIcon(name = "") {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["xlsx", "xlsm", "csv"].includes(extension)) return FileSpreadsheet;
  if (extension === "pptx") return FileChartColumn;
  if (extension === "pdf") return FileArchive;
  if (["md", "markdown", "txt", "html", "htm"].includes(extension)) return FileText;
  return File;
}

export default function KnowledgePage() {
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [activeKbId, setActiveKbId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState("");
  const [notifications, setNotifications] = useState([]);
  const fileRef = useRef(null);
  const replaceRef = useRef(null);
  const [replacingDocument, setReplacingDocument] = useState(null);
  const [versionDialog, setVersionDialog] = useState(null);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("mneme.uploadQueue") || "[]");
      if (Array.isArray(saved)) setUploadQueue(saved.slice(0, 20));
    } catch {
      window.localStorage.removeItem("mneme.uploadQueue");
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem("mneme.uploadQueue", JSON.stringify(uploadQueue.slice(0, 20)));
  }, [uploadQueue]);

  const activeKb = knowledgeBases.find((item) => item.id === activeKbId);

  async function loadBases() {
    const items = await endpoints.knowledgeBases();
    setKnowledgeBases(items || []);
    setActiveKbId((current) => current || items?.[0]?.id || null);
  }

  useEffect(() => {
    loadBases()
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let active = true;
    endpoints.notifications().then((items) => {
      if (active) setNotifications(items || []);
    }).catch(() => {});
    const stream = openNotificationStream((item) => {
      if (!active || !item) return;
      setNotifications((current) => [item, ...current.filter((entry) => entry.task_id !== item.task_id)].slice(0, 30));
      if (activeKbId && ["completed", "failed"].includes(item.status)) {
        endpoints.documents(activeKbId).then(setDocuments).catch(() => {});
      }
    });
    return () => { active = false; stream.close(); };
  }, [activeKbId]);

  useEffect(() => {
    if (!activeKbId) {
      setDocuments([]);
      return;
    }
    endpoints
      .documents(activeKbId)
      .then(setDocuments)
      .catch((requestError) => setError(requestError.message));
  }, [activeKbId]);

  useEffect(() => {
    const pending = documents.filter((item) =>
      ["parsing", "processing"].includes(item.status),
    );
    if (!pending.length) return undefined;
    const timer = window.setInterval(async () => {
      const updates = await Promise.all(
        pending.map((item) =>
          endpoints.documentStatus(item.id).catch(() => item),
        ),
      );
      setDocuments((current) =>
        current.map(
          (item) => updates.find((update) => update.id === item.id) || item,
        ),
      );
    }, 1800);
    return () => window.clearInterval(timer);
  }, [documents]);

  async function createBase(event) {
    event.preventDefault();
    const created = await endpoints.createKnowledgeBase(form);
    setKnowledgeBases((current) => [created, ...current]);
    setActiveKbId(created.id);
    setForm({ name: "", description: "" });
    setDialogOpen(false);
  }

  async function upload(files) {
    if (!activeKbId || !files?.length) return;
    const queue = Array.from(files).map((file, index) => ({
      id: `${file.name}-${file.size}-${index}`,
      name: file.name,
      status: "pending",
      message: "等待上传",
    }));
    setUploadQueue(queue);
    setUploading(true);
    setError("");
    try {
      for (const [index, file] of Array.from(files).entries()) {
        setUploadQueue((current) => current.map((item, itemIndex) =>
          itemIndex === index ? { ...item, status: "uploading", message: "正在提交解析任务" } : item));
        try {
          const document = await endpoints.uploadDocument(activeKbId, file);
          setDocuments((current) => [document, ...current]);
          setUploadQueue((current) => current.map((item, itemIndex) =>
            itemIndex === index ? { ...item, status: "success", message: "已提交，等待解析" } : item));
        } catch (requestError) {
          setUploadQueue((current) => current.map((item, itemIndex) =>
            itemIndex === index ? { ...item, status: "failed", message: requestError.message } : item));
          throw requestError;
        }
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function deleteBase() {
    if (
      !activeKbId ||
      !window.confirm(`删除“${activeKb?.name}”及其全部向量数据？`)
    )
      return;
    await endpoints.deleteKnowledgeBase(activeKbId);
    const remaining = knowledgeBases.filter((item) => item.id !== activeKbId);
    setKnowledgeBases(remaining);
    setActiveKbId(remaining[0]?.id || null);
  }

  async function deleteDocument(document) {
    if (!window.confirm(`删除“${document.fileName}”及其检索片段？`)) return;
    try {
      setError("");
      await endpoints.deleteDocument(document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "deleting" } : item));
      window.setTimeout(() => setDocuments((current) => current.filter((item) => item.id !== document.id)), 2200);
    } catch (requestError) { setError(requestError.message); }
  }

  async function reparseDocument(document) {
    try {
      setError("");
      await endpoints.reparseDocument(document.id);
      setDocuments((current) => current.map((item) => item.id === document.id ? { ...item, status: "parsing", errorMessage: null, chunkCount: 0 } : item));
    } catch (requestError) { setError(requestError.message); }
  }

  async function replaceDocument(file) {
    if (!file || !replacingDocument) return;
    try {
      setError("");
      const updated = await endpoints.replaceDocument(replacingDocument.id, file);
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) { setError(requestError.message); }
    finally {
      setReplacingDocument(null);
      if (replaceRef.current) replaceRef.current.value = "";
    }
  }

  async function showVersions(document) {
    try {
      setVersionDialog({ document, versions: null });
      const versions = await endpoints.documentVersions(document.id);
      setVersionDialog({ document, versions: versions || [] });
    } catch (requestError) {
      setVersionDialog(null);
      setError(requestError.message);
    }
  }

  async function restoreVersion(version) {
    if (!versionDialog || !window.confirm(`恢复到 v${version.version_number} 并重新建立索引？`)) return;
    try {
      const updated = await endpoints.restoreDocumentVersion(versionDialog.document.id, version.version_number);
      setDocuments((current) => current.map((item) => item.id === updated.id ? updated : item));
      setVersionDialog(null);
    } catch (requestError) { setError(requestError.message); }
  }

  const visibleDocuments = useMemo(
    () =>
      documents.filter((item) =>
        item.fileName.toLowerCase().includes(query.toLowerCase()),
      ),
    [documents, query],
  );
  const readyCount = documents.filter((item) => item.status === "ready").length;
  const chunkCount = documents.reduce(
    (sum, item) => sum + (item.chunkCount || 0),
    0,
  );

  return (
    <div className="knowledge-page">
      <header className="knowledge-masthead">
        <div>
          <p className="eyebrow">知识资料管理</p>
          <h1>资料库</h1>
          <p>把课件、笔记与复杂文档整理成可追溯的检索依据。</p>
        </div>
        <button onClick={() => setDialogOpen(true)}>
          <FolderPlus size={18} />
          新建资料库
        </button>
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
            <span>资料库</span>
            <strong>{knowledgeBases.length.toString().padStart(2, "0")}</strong>
          </div>
          {loading ? (
            <LoadingState />
          ) : knowledgeBases.length ? (
            knowledgeBases.map((kb, index) => (
              <button
                key={kb.id}
                onClick={() => setActiveKbId(kb.id)}
                className={kb.id === activeKbId ? "active" : ""}
              >
                <span className="kb-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>
                  <strong>{kb.name}</strong>
                  <small>{kb.description || "未填写说明"}</small>
                </span>
                <ArrowUpRight size={17} />
              </button>
            ))
          ) : (
            <div className="kb-empty">
              <Archive size={28} />
              <p>还没有资料库</p>
            </div>
          )}
        </aside>

        <main className="document-workbench">
          {activeKb ? (
            <>
              <div className="workbench-head">
                <div>
                  <span>当前资料库</span>
                  <h2>{activeKb.name}</h2>
                </div>
                <button
                  className="danger-icon"
                  onClick={deleteBase}
                  title="删除资料库"
                >
                  <Trash2 size={18} />
                </button>
              </div>
              <div className="knowledge-metrics">
                <div>
                  <strong>{documents.length}</strong>
                  <span>文档</span>
                </div>
                <div>
                  <strong>{readyCount}</strong>
                  <span>可检索</span>
                </div>
                <div>
                  <strong>{chunkCount}</strong>
                  <span>语义片段</span>
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
                    {uploading ? "正在提交解析任务" : "拖放文件到这里"}
                  </strong>
                  <span>支持文档、演示文稿、表格、纯文本和网页文件</span>
                </div>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? "处理中" : "选择文件"}
                </button>
              </div>
              <div className="document-toolbar">
                <div className="document-search">
                  <Search size={17} />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="筛选文档"
                  />
                </div>
                <span>{visibleDocuments.length} 份文档</span>
              </div>
              {uploadQueue.length > 0 && (
                <div className="upload-queue" aria-live="polite">
                  {uploadQueue.map((item) => (
                    <div className={`upload-queue-item ${item.status}`} key={item.id}>
                      <strong>{item.name}</strong>
                      <span>{item.message}</span>
                    </div>
                  ))}
                </div>
              )}
              {notifications.length > 0 && (
                <div className="task-notifications" aria-live="polite">
                  <div><strong>处理通知</strong><span>服务端任务状态会在这里更新</span></div>
                  {notifications.slice(0, 5).map((item) => (
                    <div className={`task-notification ${item.status}`} key={item.task_id}>
                      <strong>{item.task_type === "document_ingest" ? "文档解析" : item.task_type === "document_delete" ? "文档删除" : "资料库任务"}</strong>
                      <StatusBadge status={item.status} />
                      <span>{item.error_message || (item.status === "completed" ? "已完成" : item.status === "failed" ? "处理失败，可在工作台重试" : "处理中")}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="document-table">
                <div className="document-row document-header">
                  <span>文件</span>
                  <span>状态</span>
                  <span>片段</span>
                  <span>更新时间</span>
                  <span />
                </div>
                {visibleDocuments.map((document) => {
                  const Icon = fileIcon(document.fileName);
                  return (
                    <div className="document-row" key={document.id}>
                      <span className="document-name">
                        <span className="file-icon">
                          <Icon size={19} />
                        </span>
                        <span>
                          <strong>{document.fileName}</strong>
                          <small>
                            {document.errorMessage || `文档编号 ${document.id}`}
                          </small>
                        </span>
                      </span>
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
                          : "刚刚"}
                      </span>
                      <span>
                        {!["deleting", "parsing"].includes(document.status) && <>
                          <button title="版本历史" onClick={() => showVersions(document)}>
                            <History size={16} />
                          </button>
                          <button title="替换文件" onClick={() => { setReplacingDocument(document); replaceRef.current?.click(); }}>
                            <RefreshCw size={16} />
                          </button>
                          <button title="重新解析" onClick={() => reparseDocument(document)}>
                            <ArrowUpRight size={16} />
                          </button>
                          <button title="删除文档" onClick={() => deleteDocument(document)}>
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
                    <strong>这里还没有资料</strong>
                    <span>上传后可以在对话中选择该资料库进行检索。</span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="select-kb-empty">
              <BookCopy size={42} />
              <h2>建立第一个资料库</h2>
              <p>不同课程或主题建议分别管理。</p>
              <button onClick={() => setDialogOpen(true)}>
                <Plus size={17} />
                新建资料库
              </button>
            </div>
          )}
          {error && <div className="page-error">{error}</div>}
        </main>
      </div>

      {dialogOpen && (
        <div
          className="dialog-backdrop"
          onMouseDown={() => setDialogOpen(false)}
        >
          <form
            className="kb-dialog"
            onSubmit={createBase}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>新资料库</span>
                <h2>新建资料库</h2>
              </div>
              <button type="button" onClick={() => setDialogOpen(false)}>
                <X size={18} />
              </button>
            </header>
            <label>
              <span>名称</span>
              <input
                autoFocus
                required
                maxLength={100}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder="例如：机器学习基础"
              />
            </label>
            <label>
              <span>说明</span>
              <textarea
                rows={4}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
                placeholder="记录资料范围与学习目标"
              />
            </label>
            <button className="dialog-submit">
              创建资料库
              <ArrowUpRight size={17} />
            </button>
          </form>
        </div>
      )}
      {versionDialog && (
        <div className="dialog-backdrop" onMouseDown={() => setVersionDialog(null)}>
          <section className="kb-dialog version-dialog" onMouseDown={(event) => event.stopPropagation()}>
            <header>
              <div><span>版本历史</span><h2>{versionDialog.document.fileName}</h2></div>
              <button type="button" onClick={() => setVersionDialog(null)}><X size={18} /></button>
            </header>
            <div className="version-list">
              {versionDialog.versions === null && <LoadingState label="正在读取版本" />}
              {versionDialog.versions?.map((version) => (
                <button key={version.version_number} disabled={Boolean(version.active)} onClick={() => restoreVersion(version)}>
                  <span>
                    <strong>v{version.version_number} · {version.file_name}</strong>
                    <small>{String(version.sha256).slice(0, 12)} · {new Date(version.created_at).toLocaleString("zh-CN")}</small>
                  </span>
                  <StatusBadge status={version.active ? "active" : "ready"} />
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
