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
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { endpoints } from "../api/client";
import LoadingState from "../components/LoadingState";
import StatusBadge from "../components/StatusBadge";
import "../styles/knowledge.css";

function fileIcon(name = "") {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["xlsx", "xlsm", "csv"].includes(extension)) return FileSpreadsheet;
  if (extension === "pptx") return FileChartColumn;
  if (extension === "pdf") return FileArchive;
  if (["md", "txt", "html"].includes(extension)) return FileText;
  return File;
}

export default function KnowledgePage() {
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [activeKbId, setActiveKbId] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState("");
  const fileRef = useRef(null);

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
    setUploading(true);
    setError("");
    try {
      for (const file of files) {
        const document = await endpoints.uploadDocument(activeKbId, file);
        setDocuments((current) => [document, ...current]);
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
                        <button title="更多">
                          <MoreHorizontal size={17} />
                        </button>
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
    </div>
  );
}
