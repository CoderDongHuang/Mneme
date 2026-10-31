import { useFormatters } from '../hooks/useFormatters'
import { t, useI18n } from '../i18n'
import { BookMarked, GitBranch, RefreshCw, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { documentFileUrl, endpoints } from '../api/client';
import LoadingState from "../components/LoadingState";
import ParsePreview from '../components/ParsePreview';
import RetrievalFilters, { emptyFilters } from '../components/RetrievalFilters';
import StatusBadge from "../components/StatusBadge";

import "../styles/workspace.css";

const modes = [["reader", "引用阅读", BookMarked], ["debug", "检索调试", Search], ["branch", "分支对比", GitBranch]];
const roleLabels = { user: "我", assistant: "忆知", system: "系统" };


export default function WorkspaceTools({ initialMode }) {
  const fmt = useFormatters()
  useI18n();
  const location = useLocation();
  const [mode, setMode] = useState(initialMode || "reader");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [kbId, setKbId] = useState("");
  const [documents, setDocuments] = useState([]);
  const [preview, setPreview] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [branches, setBranches] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [debugResult, setDebugResult] = useState(null);
  const [retrievalFilters, setRetrievalFilters] = useState({ ...emptyFilters });
  const [debugQuery, setDebugQuery] = useState("");
  const [branchForm, setBranchForm] = useState({
    source_session_id: "",
    label: "",
  });
  const [highlight, setHighlight] = useState("");
  const [previewPage, setPreviewPage] = useState("");

  const mounted = useRef(false);
  const documentRequest = useRef(0);
  const previewRequest = useRef(0);
  const actionLock = useRef(false);
  async function loadAll() {
    setLoading(true); setError("");
    const results = await Promise.allSettled([endpoints.knowledgeBases(), endpoints.sessions(), endpoints.branches()]);
    if (!mounted.current) return;
    if (results[0].status === 'fulfilled') { setKnowledgeBases(results[0].value || []); setKbId(current => current || String(results[0].value?.[0]?.id || '')); }
    if (results[1].status === 'fulfilled') setSessions(results[1].value || []);
    if (results[2].status === 'fulfilled') setBranches(results[2].value || []);
    setError(results.filter(r => r.status === 'rejected').map(r => r.reason.message).join(' · ')); setLoading(false);
  }
  useEffect(() => { const previews = previewRequest, documents = documentRequest; mounted.current = true; void loadAll(); return () => { mounted.current = false; previews.current++; documents.current++; } }, []);
  useEffect(() => {
    const version = ++documentRequest.current;
    setDocuments([]);
    if (kbId) endpoints.documents(kbId).then(items => { if (mounted.current && version === documentRequest.current) setDocuments(items || []); }).catch(e => { if (mounted.current && version === documentRequest.current) setError(e.message); });
  }, [kbId]);
  async function openDocument(id, page = '', text = '', sha) {
    const version = ++previewRequest.current;
    setPreview(null); setError(''); setHighlight(text); setPreviewPage(page);
    try { const data = await endpoints.documentPreview(id, sha); if (mounted.current && version === previewRequest.current) setPreview(data); }
    catch (e) { if (mounted.current && version === previewRequest.current) setError(e.message); }
  }
  useEffect(() => {
    const request = previewRequest;
    const params = new URLSearchParams(location.search);
    const documentId = params.get("document");
    if (!documentId) return;
    setMode("reader");
    setHighlight(params.get("highlight") || "");
    setPreviewPage(params.get("page") || "");
    void openDocument(documentId, params.get('page') || '', params.get('highlight') || '', params.get('sha256'));
    return () => { request.current++; };
  }, [location.search]);

  async function run(action) {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      actionLock.current = false; setBusy(false);
    }
  }

  async function changeKb(value) {
    setKbId(value);
    setRetrievalFilters({ ...emptyFilters });
    setDebugResult(null);
    previewRequest.current++; setPreview(null);
  }
  async function createBranch(event) {
    event.preventDefault();
    await run(async () => {
      await endpoints.createBranch(branchForm);
      setBranches(await endpoints.branches());
      setBranchForm({ source_session_id: "", label: "" });
    });
  }


  return (
    <div className="workspace-page">
      <header className="workspace-head">
        <div>
          <p className="eyebrow">{t("一体化学习工作台")}</p>
          <h1>{t("学习工作台")}</h1>
          <p>{t("阅读原文、核对引用，探索检索结果与对话分支。")}</p>
        </div>
        <button onClick={loadAll} title={t("刷新")} disabled={busy}>
          <RefreshCw size={18} />
        </button>
      </header>
      <nav className="workspace-modes" aria-label={t("工作台模式")}>
        {modes.map(([id, label, Icon]) => (
          <button
            key={id}
            className={mode === id ? "active" : ""}
            onClick={() => setMode(id)}
            aria-label={t(label)}
            title={t(label)}
          >
            <Icon size={17} />
            <span>{t(label)}</span>
          </button>
        ))}
      </nav>
      {error && <div className="page-error">{error}</div>}
      {notice && <div className="page-notice">{notice}</div>}
      {loading ? (
        <LoadingState label={t("正在装载学习工作台")} />
      ) : (
        <div className="workspace-canvas">
          {mode === "reader" && (
            <section className="studio-layout">
              <aside>
                <h2>{t("文档")}</h2>
                <select aria-label={t("资料库")} value={kbId} onChange={(e) => changeKb(e.target.value)}>
                  {knowledgeBases.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
                {documents.map((d) => (
                  <button
                    key={d.id}
                    className={preview?.document?.id === d.id ? "active" : ""}
                    onClick={() => openDocument(d.id)}
                  >
                    <span>{d.fileName}</span>
                    <StatusBadge status={d.status} />
                  </button>
                ))}
              </aside>
              <article className="reader-pane">
                {preview ? (
                  <>
                    <header>
                      <div>
                        <span>{t("文档编号 ")}{preview.document.id}</span>
                        <h2>{preview.document.file_name}</h2>
                      </div>
                      <small>{preview.extension.toUpperCase()}</small>
                    </header>
                    {(preview.parse_report?.pages || []).some((page) =>
                      page.ocr_confidence_min != null && page.ocr_confidence_min < 0.7
                    ) && (
                      <div className="parse-warning" role="alert">
                        <strong>{t("部分页面识别置信度较低")}</strong>
                        <span>{t(" 请重点核对第 ")}{(preview.parse_report.pages || [])
                            .filter((page) => page.ocr_confidence_min != null && page.ocr_confidence_min < 0.7)
                            .map((page) => page.page)
                            .join("、")}{t(" 页的引用原文。 ")}</span>
                      </div>
                    )}
                    {preview.extension === "pdf" ? (
                      <iframe
                        className="document-frame"
                        src={documentFileUrl(preview.document.id, previewPage, preview.document.sha256)}
                        title={t("{0} PDF 预览", [preview.document.file_name])}
                      />
                    ) : (
                      <pre>{highlight && preview.content.includes(highlight) ? preview.content.split(highlight).map((part, index, parts) => <span key={`${index}-${part.slice(0, 12)}`}>{part}{index < parts.length - 1 && <mark>{highlight}</mark>}</span>) : preview.content}</pre>
                    )}
                    <ParsePreview key={`${preview.document.id}-${preview.document.sha256 || ''}-${previewPage}`} preview={preview} initialPage={previewPage} />
                  </>
                ) : (
                  <div className="studio-empty">
                    <BookMarked size={32} />
                    <h2>{t("选择文档开始阅读")}</h2>
                    <p>{t("回答中的页码、章节和语义片段可与这里的原文交叉核对。")}</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {mode === "debug" && (
            <section className="debugger">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(async () =>
                    setDebugResult(
                      await endpoints.retrievalDebug(kbId, debugQuery, 8, retrievalFilters),
                    ),
                  );
                }}
              >
                <select aria-label={t("资料库")} value={kbId} onChange={(e) => { setKbId(e.target.value); setRetrievalFilters({ ...emptyFilters }); setDebugResult(null); }}>
                  {knowledgeBases.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
                <RetrievalFilters key={kbId} kbIds={kbId ? [kbId] : []} value={retrievalFilters} onChange={setRetrievalFilters} />
                <input
                  value={debugQuery}
                  onChange={(e) => setDebugQuery(e.target.value)}
                  placeholder={t("输入检索问题")}
                  required
                />
                <button disabled={busy || !kbId}>
                  <Search size={17} />{t(" 运行检索 ")}</button>
              </form>
              <div className="retrieval-results">
                {debugResult?.chunks?.length === 0 && <p role="status">{t("当前筛选范围没有命中资料，请调整筛选条件或检索问题。")}</p>}
                {debugResult?.chunks?.map((chunk, index) => (
                  <article key={chunk.id || index}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <header>
                        <strong>{chunk.metadata?.source || t("未知来源")}</strong>
                        <small>{t(" 排序信号 ")}{fmt.decimal(chunk.score, 4)}{t(" · 第")}{" "}
                          {chunk.metadata?.page || "-"}{t(" 页 ")}</small>
                      </header>
                      <p>{chunk.content}</p>
                      <small>{Object.entries(chunk.retrieval_ranks || {}).map(([channel, rank]) => `${channel} #${rank}`).join(' · ')}</small>
                      <code>
                        {chunk.metadata?.section || chunk.metadata?.chunk_type}
                      </code>
                    </div>
                  </article>
                )) || (
                  <div className="studio-empty">
                    <Search size={32} />
                    <h2>{t("观察真实召回结果")}</h2>
                  </div>
                )}
              </div>
            </section>
          )}

          {mode === "branch" && (
            <section className="branch-layout">
              <form onSubmit={createBranch}>
                <h2>{t("从会话创建分支")}</h2>
                <select
                  value={branchForm.source_session_id}
                  onChange={(e) =>
                    setBranchForm({
                      ...branchForm,
                      source_session_id: e.target.value,
                    })
                  }
                  required
                >
                  <option value="">{t("选择原会话")}</option>
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
                <input
                  placeholder={t("分支名称")}
                  value={branchForm.label}
                  onChange={(e) =>
                    setBranchForm({ ...branchForm, label: e.target.value })
                  }
                  required
                />
                <button disabled={busy}>{t("创建分支")}</button>
                <div>
                  {branches.map((branch) => (
                    <button
                      type="button"
                      key={branch.id}
                      onClick={() =>
                        run(async () =>
                          setComparison(
                            await endpoints.compareBranch(branch.id),
                          ),
                        )
                      }
                    >
                      <GitBranch size={15} />
                      {branch.label}
                    </button>
                  ))}
                </div>
              </form>
              <div className="branch-compare">
                {comparison ? (
                  <>
                    {["source_messages", "branch_messages"].map(
                      (side, index) => (
                        <section key={side}>
                          <h2>{index ? t("分支回答") : t("原始回答")}</h2>
                          {comparison[side].map((message) => (
                            <article key={message.id}>
                                <span>{roleLabels[message.role] || message.role}</span>
                              <p>{message.content}</p>
                            </article>
                          ))}
                        </section>
                      ),
                    )}
                  </>
                ) : (
                  <div className="studio-empty">
                    <GitBranch size={32} />
                    <h2>{t("选择分支并排比较")}</h2>
                  </div>
                )}
              </div>
            </section>
          )}

        </div>
      )}
      {busy && (
        <div className="workspace-busy">
          <RefreshCw size={18} />
          <span>{t("正在处理")}</span>
        </div>
      )}
    </div>
  );
}
