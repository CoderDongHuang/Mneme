import {
  ArchiveRestore,
  BookMarked,
  BrainCircuit,
  Check,
  ClipboardCheck,
  Download,
  GitBranch,
  Play,
  RefreshCw,
  Search,
  Snowflake,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { downloadWorkspaceExport, endpoints } from "../api/client";
import LoadingState from "../components/LoadingState";
import StatusBadge from "../components/StatusBadge";
import "../styles/workspace.css";

const modes = [
  ["reader", "引用阅读", BookMarked],
  ["plan", "计划复习", ClipboardCheck],
  ["quiz", "知识测验", Check],
  ["tasks", "处理中心", RefreshCw],
  ["debug", "检索调试", Search],
  ["memory", "记忆管理", BrainCircuit],
  ["branch", "分支对比", GitBranch],
  ["data", "数据迁移", ArchiveRestore],
];

function json(value, fallback = []) {
  if (typeof value !== "string") return value || fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

const statusLabels = {
  active: "进行中",
  completed: "已完成",
  pending: "等待中",
  processing: "处理中",
  retry: "等待重试",
  failed: "处理失败",
};

const roleLabels = { user: "我", assistant: "忆知", system: "系统" };
const categoryLabels = {
  preference: "表达偏好",
  weak_point: "薄弱点",
  progress: "学习进度",
};

export default function WorkspacePage() {
  const [mode, setMode] = useState("reader");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [kbId, setKbId] = useState("");
  const [documents, setDocuments] = useState([]);
  const [preview, setPreview] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [plans, setPlans] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
  const [quiz, setQuiz] = useState(null);
  const [answers, setAnswers] = useState([]);
  const [quizResult, setQuizResult] = useState(null);
  const [memories, setMemories] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [branches, setBranches] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [debugResult, setDebugResult] = useState(null);
  const [planForm, setPlanForm] = useState({
    title: "",
    goal: "",
    target_date: "",
  });
  const [topic, setTopic] = useState("");
  const [debugQuery, setDebugQuery] = useState("");
  const [branchForm, setBranchForm] = useState({
    source_session_id: "",
    label: "",
  });
  const [importText, setImportText] = useState("");

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      const [
        kbs,
        taskItems,
        planItems,
        reviewItems,
        quizItems,
        memoryData,
        sessionItems,
        branchItems,
      ] = await Promise.all([
        endpoints.knowledgeBases(),
        endpoints.tasks(),
        endpoints.plans(),
        endpoints.reviews(),
        endpoints.quizzes(),
        endpoints.managedMemories(),
        endpoints.sessions(),
        endpoints.branches(),
      ]);
      setKnowledgeBases(kbs || []);
      setTasks(taskItems || []);
      setPlans(planItems || []);
      setReviews(reviewItems || []);
      setQuizzes(quizItems || []);
      setMemories(memoryData?.memories || memoryData?.data?.memories || []);
      setSessions(sessionItems || []);
      setBranches(branchItems || []);
      const initialKb = String(kbs?.[0]?.id || "");
      setKbId((current) => current || initialKb);
      if (initialKb) setDocuments(await endpoints.documents(initialKb));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeKb(value) {
    setKbId(value);
    setDocuments(value ? await endpoints.documents(value) : []);
  }
  async function createPlan(event) {
    event.preventDefault();
    await run(async () => {
      await endpoints.createPlan(planForm);
      setPlanForm({ title: "", goal: "", target_date: "" });
      setPlans(await endpoints.plans());
      setReviews(await endpoints.reviews());
    });
  }
  async function generateQuiz(event) {
    event.preventDefault();
    await run(async () => {
      const created = await endpoints.generateQuiz({ kb_id: kbId, topic });
      setQuiz(created);
      setAnswers([]);
      setQuizResult(null);
      setQuizzes(await endpoints.quizzes());
    });
  }
  async function submitQuiz() {
    await run(async () =>
      setQuizResult(await endpoints.submitQuiz(quiz.id, answers)),
    );
  }
  async function createBranch(event) {
    event.preventDefault();
    await run(async () => {
      await endpoints.createBranch(branchForm);
      setBranches(await endpoints.branches());
      setBranchForm({ source_session_id: "", label: "" });
    });
  }

  const questions = useMemo(() => json(quiz?.questions_json, []), [quiz]);

  return (
    <div className="workspace-page">
      <header className="workspace-head">
        <div>
          <p className="eyebrow">一体化学习工作台</p>
          <h1>学习工作台</h1>
          <p>从资料依据到复习、测验与长期记忆，在一个连续工作流中完成。</p>
        </div>
        <button onClick={loadAll} title="刷新" disabled={busy}>
          <RefreshCw size={18} />
        </button>
      </header>
      <nav className="workspace-modes" aria-label="工作台模式">
        {modes.map(([id, label, Icon]) => (
          <button
            key={id}
            className={mode === id ? "active" : ""}
            onClick={() => setMode(id)}
            aria-label={label}
            title={label}
          >
            <Icon size={17} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      {error && <div className="page-error">{error}</div>}
      {loading ? (
        <LoadingState label="正在装载学习工作台" />
      ) : (
        <main className="workspace-canvas">
          {mode === "reader" && (
            <section className="studio-layout">
              <aside>
                <h2>文档</h2>
                <select value={kbId} onChange={(e) => changeKb(e.target.value)}>
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
                    onClick={() =>
                      run(async () =>
                        setPreview(await endpoints.documentPreview(d.id)),
                      )
                    }
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
                        <span>文档编号 {preview.document.id}</span>
                        <h2>{preview.document.file_name}</h2>
                      </div>
                      <small>{preview.extension.toUpperCase()}</small>
                    </header>
                    <pre>{preview.content}</pre>
                  </>
                ) : (
                  <div className="studio-empty">
                    <BookMarked size={32} />
                    <h2>选择文档开始阅读</h2>
                    <p>回答中的页码、章节和语义片段可与这里的原文交叉核对。</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {mode === "plan" && (
            <section className="plan-grid">
              <form onSubmit={createPlan}>
                <p className="eyebrow">新学习计划</p>
                <h2>建立学习节奏</h2>
                <input
                  placeholder="计划名称"
                  value={planForm.title}
                  onChange={(e) =>
                    setPlanForm({ ...planForm, title: e.target.value })
                  }
                  required
                />
                <textarea
                  placeholder="学习目标"
                  value={planForm.goal}
                  onChange={(e) =>
                    setPlanForm({ ...planForm, goal: e.target.value })
                  }
                  required
                />
                <input
                  type="date"
                  value={planForm.target_date}
                  onChange={(e) =>
                    setPlanForm({ ...planForm, target_date: e.target.value })
                  }
                />
                <button disabled={busy}>生成计划与复习卡</button>
              </form>
              <div className="review-stream">
                <header>
                  <h2>今日复习</h2>
                  <span>{reviews.length} 张卡片</span>
                </header>
                {reviews.map((card) => (
                  <article key={card.id}>
                    <div>
                      <small>
                        {card.due_at
                          ? new Date(card.due_at).toLocaleDateString("zh-CN")
                          : "今天"}
                      </small>
                      <strong>{card.prompt}</strong>
                      <p>{card.answer}</p>
                    </div>
                    <div className="rating">
                      {[1, 3, 5].map((rate) => (
                        <button
                          key={rate}
                          title={`掌握度 ${rate}`}
                          onClick={() =>
                            run(async () => {
                              await endpoints.reviewCard(card.id, rate);
                              setReviews(await endpoints.reviews());
                            })
                          }
                        >
                          {rate}
                        </button>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
              <div className="plan-list">
                <h2>计划</h2>
                {plans.map((plan) => (
                  <article key={plan.id}>
                      <span>{statusLabels[plan.status] || plan.status}</span>
                    <strong>{plan.title}</strong>
                    <p>{plan.goal}</p>
                  </article>
                ))}
              </div>
            </section>
          )}

          {mode === "quiz" && (
            <section className="quiz-layout">
              <form onSubmit={generateQuiz}>
                <h2>从资料生成测验</h2>
                <select value={kbId} onChange={(e) => setKbId(e.target.value)}>
                  {knowledgeBases.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
                <input
                  placeholder="测验主题"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  required
                />
                <button disabled={busy || !kbId}>生成测验</button>
                <div className="quiz-history">
                  {quizzes.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      onClick={() => {
                        setQuiz(item);
                        setAnswers([]);
                        setQuizResult(null);
                      }}
                    >
                      {item.title}
                    </button>
                  ))}
                </div>
              </form>
              <div className="quiz-sheet">
                {quiz ? (
                  <>
                    <header>
                      <h2>{quiz.title}</h2>
                      {quizResult && <strong>{quizResult.score} 分</strong>}
                    </header>
                    {questions.map((q, index) => (
                      <article key={q.id}>
                        <span>0{index + 1}</span>
                        <h3>{q.prompt}</h3>
                        {q.type === "choice" ? (
                          q.options.map((option, optionIndex) => (
                            <label key={option}>
                              <input
                                type="radio"
                                name={`q-${index}`}
                                checked={answers[index] === String(optionIndex)}
                                onChange={() =>
                                  setAnswers((current) => {
                                    const next = [...current];
                                    next[index] = String(optionIndex);
                                    return next;
                                  })
                                }
                              />
                              {option}
                            </label>
                          ))
                        ) : (
                          <textarea
                            value={answers[index] || ""}
                            onChange={(e) =>
                              setAnswers((current) => {
                                const next = [...current];
                                next[index] = e.target.value;
                                return next;
                              })
                            }
                          />
                        )}
                      </article>
                    ))}
                    <button onClick={submitQuiz} disabled={busy}>
                      提交答案
                    </button>
                  </>
                ) : (
                  <div className="studio-empty">
                    <ClipboardCheck size={32} />
                    <h2>生成一次针对性测验</h2>
                  </div>
                )}
              </div>
            </section>
          )}

          {mode === "tasks" && (
            <section className="task-center">
              <header>
                <h2>文档处理中心</h2>
                <p>查看持久化任务的尝试次数、错误和重试状态。</p>
              </header>
              {tasks.map((task) => (
                <article key={task.task_id}>
                  <div>
                    <StatusBadge status={task.status} />
                    <strong>{task.file_name || task.task_type}</strong>
                    <small>{task.task_id}</small>
                  </div>
                  <span>
                    {task.attempt_count}/{task.max_attempts}
                  </span>
                  <p>{task.error_message || "处理链路正常"}</p>
                  {["failed", "retry"].includes(task.status) && (
                    <button
                      onClick={() =>
                        run(async () => {
                          await endpoints.retryTask(task.task_id);
                          setTasks(await endpoints.tasks());
                        })
                      }
                    >
                      <RefreshCw size={15} />
                      重试
                    </button>
                  )}
                </article>
              ))}
            </section>
          )}

          {mode === "debug" && (
            <section className="debugger">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(async () =>
                    setDebugResult(
                      await endpoints.retrievalDebug(kbId, debugQuery, 8),
                    ),
                  );
                }}
              >
                <select value={kbId} onChange={(e) => setKbId(e.target.value)}>
                  {knowledgeBases.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.name}
                    </option>
                  ))}
                </select>
                <input
                  value={debugQuery}
                  onChange={(e) => setDebugQuery(e.target.value)}
                  placeholder="输入检索问题"
                  required
                />
                <button>
                  <Search size={17} />
                  运行检索
                </button>
              </form>
              <div className="retrieval-results">
                {debugResult?.chunks?.map((chunk, index) => (
                  <article key={chunk.id || index}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <header>
                        <strong>{chunk.metadata?.source || "未知来源"}</strong>
                        <small>
                          相似度 {Number(chunk.score || 0).toFixed(4)} · 第{" "}
                          {chunk.metadata?.page || "-"} 页
                        </small>
                      </header>
                      <p>{chunk.content}</p>
                      <code>
                        {chunk.metadata?.section || chunk.metadata?.chunk_type}
                      </code>
                    </div>
                  </article>
                )) || (
                  <div className="studio-empty">
                    <Search size={32} />
                    <h2>观察真实召回结果</h2>
                  </div>
                )}
              </div>
            </section>
          )}

          {mode === "memory" && (
            <section className="memory-manager">
              <header>
                <h2>长期记忆控制</h2>
                <p>冻结后该记忆仍保留，但不会进入助手上下文。</p>
              </header>
              {memories.map((memory) => (
                <article key={memory.id}>
                  <div>
                    <span>{categoryLabels[memory.category] || memory.category}</span>
                    <input
                      defaultValue={memory.content}
                      onBlur={(e) => {
                        if (e.target.value !== memory.content)
                          run(async () => {
                            const data = await endpoints.updateManagedMemory(
                              memory.id,
                              { content: e.target.value },
                            );
                            setMemories(
                              data?.memories || data?.data?.memories || [],
                            );
                          });
                      }}
                    />
                    <small>{memory.topic || "未分类"}</small>
                  </div>
                  <button
                    onClick={() =>
                      run(async () => {
                        const data = await endpoints.updateManagedMemory(
                          memory.id,
                          { frozen: !memory.frozen },
                        );
                        setMemories(
                          data?.memories || data?.data?.memories || [],
                        );
                      })
                    }
                    title={memory.frozen ? "解冻" : "冻结"}
                  >
                    {memory.frozen ? (
                      <Play size={17} />
                    ) : (
                      <Snowflake size={17} />
                    )}
                  </button>
                  <button
                    onClick={() =>
                      run(async () => {
                        const data = await endpoints.deleteManagedMemory(
                          memory.id,
                        );
                        setMemories(
                          data?.memories || data?.data?.memories || [],
                        );
                      })
                    }
                    title="删除"
                  >
                    <Trash2 size={17} />
                  </button>
                </article>
              ))}
            </section>
          )}

          {mode === "branch" && (
            <section className="branch-layout">
              <form onSubmit={createBranch}>
                <h2>从会话创建分支</h2>
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
                  <option value="">选择原会话</option>
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
                <input
                  placeholder="分支名称"
                  value={branchForm.label}
                  onChange={(e) =>
                    setBranchForm({ ...branchForm, label: e.target.value })
                  }
                  required
                />
                <button>创建分支</button>
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
                          <h2>{index ? "分支回答" : "原始回答"}</h2>
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
                    <h2>选择分支并排比较</h2>
                  </div>
                )}
              </div>
            </section>
          )}

          {mode === "data" && (
            <section className="data-transfer">
              <article>
                <Download size={30} />
                <h2>导出完整学习档案</h2>
                <p>包含会话、资料库目录、计划、复习、测验和分支元数据。</p>
                <button onClick={() => run(downloadWorkspaceExport)}>
                  <Download size={17} />
                  导出数据
                </button>
              </article>
              <article>
                <Upload size={30} />
                <h2>导入学习计划</h2>
                <p>
                  粘贴“忆知”导出的数据；当前导入采用追加策略，不覆盖已有数据。
                </p>
                <textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder="粘贴导出数据"
                />
                <button
                  onClick={() =>
                    run(async () => {
                      await endpoints.importData(JSON.parse(importText));
                      setPlans(await endpoints.plans());
                      setImportText("");
                    })
                  }
                >
                  <Upload size={17} />
                  开始导入
                </button>
              </article>
            </section>
          )}
        </main>
      )}
      {busy && (
        <div className="workspace-busy">
          <RefreshCw size={18} />
          <span>正在处理</span>
        </div>
      )}
    </div>
  );
}
