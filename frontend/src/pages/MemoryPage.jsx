import {
  ArrowUpRight,
  BrainCircuit,
  CalendarRange,
  CheckCircle2,
  Compass,
  Plus,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { endpoints } from "../api/client";
import LoadingState from "../components/LoadingState";
import "../styles/memory.css";

export default function MemoryPage() {
  const [memory, setMemory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(false);
  const [form, setForm] = useState({
    category: "preference",
    content: "",
    topic: "",
  });
  const [error, setError] = useState("");

  async function load() {
    try {
      setMemory(await endpoints.memory());
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function addMemory(event) {
    event.preventDefault();
    try {
      setError("");
      await endpoints.writeMemory(form);
      setDialog(false);
      setForm({ category: "preference", content: "", topic: "" });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  const stats = useMemo(
    () => ({
      preferences: memory?.preferences?.length || 0,
      weakPoints: memory?.weak_points?.length || 0,
      progress: memory?.progress ? 1 : 0,
    }),
    [memory],
  );

  return (
    <div className="memory-page">
      <header className="memory-hero">
        <div className="memory-orbit">
          <BrainCircuit size={34} />
        </div>
        <div>
          <p className="eyebrow">持续更新的学习画像</p>
          <h1>你的学习画像</h1>
          <p>由真实对话逐步形成。你始终可以确认、补充或忽略一条记忆。</p>
        </div>
        <button onClick={() => setDialog(true)}>
          <Plus size={18} />
          补充一条
        </button>
      </header>

      {loading ? (
        <LoadingState label="正在读取学习画像" />
      ) : (
        <>
          <section className="memory-scoreboard">
            <div>
              <span>偏好信号</span>
              <strong>{stats.preferences.toString().padStart(2, "0")}</strong>
              <small>决定回答呈现方式</small>
            </div>
            <div>
              <span>待加强主题</span>
              <strong>{stats.weakPoints.toString().padStart(2, "0")}</strong>
              <small>随掌握程度动态衰减</small>
            </div>
            <div>
              <span>进度锚点</span>
              <strong>{stats.progress.toString().padStart(2, "0")}</strong>
              <small>定位下一步学习位置</small>
            </div>
          </section>

          <div className="memory-grid">
            <section className="preference-field">
              <header>
                <div>
                  <Sparkles size={18} />
                  <span>表达偏好</span>
                </div>
                <h2>我如何更好地向你解释</h2>
              </header>
              <div className="preference-map">
                {memory?.preferences?.length ? (
                  memory.preferences.map((item, index) => (
                    <article key={item.id}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <p>{item.content}</p>
                      <ArrowUpRight size={16} />
                    </article>
                  ))
                ) : (
                  <div className="memory-empty">
                    <p>还没有明确偏好</p>
                    <span>例如“先给例子，再解释公式”。</span>
                  </div>
                )}
              </div>
            </section>

            <section className="progress-panel">
              <div className="progress-symbol">
                <Compass size={28} />
              </div>
              <span>当前学习位置</span>
              <h2>{memory?.progress?.topic || "等待第一个进度锚点"}</h2>
              <p>
                {memory?.progress?.content ||
                  "在对话中告诉忆知你正在学习的章节或主题。"}
              </p>
              <div className="progress-line">
                <span />
              </div>
            </section>

            <section className="weakpoint-ledger">
              <header>
                <div>
                  <Target size={19} />
                  <h2>待加强主题</h2>
                </div>
                <span>优先事项</span>
              </header>
              <div>
                {memory?.weak_points?.length ? (
                  memory.weak_points.map((item, index) => (
                    <article key={item.id}>
                      <span className="weak-rank">{index + 1}</span>
                      <div>
                        <strong>{item.topic || "未命名主题"}</strong>
                        <p>{item.content}</p>
                      </div>
                      <span className="importance">
                        <i
                          style={{
                            width: `${(item.importance || 0.5) * 100}%`,
                          }}
                        />
                      </span>
                    </article>
                  ))
                ) : (
                  <div className="memory-empty">
                    <CheckCircle2 size={27} />
                    <p>暂未识别到薄弱点</p>
                    <span>多轮学习对话后会在这里形成优先级。</span>
                  </div>
                )}
              </div>
            </section>

            <section className="memory-method">
              <CalendarRange size={21} />
              <div>
                <strong>记忆会随学习变化</strong>
                <p>
                  重复出现的困难会提高优先级，长期未出现的薄弱点会逐步衰减。
                </p>
              </div>
            </section>
          </div>
        </>
      )}
      {error && <div className="page-error">{error}</div>}

      {dialog && (
        <div className="dialog-backdrop" onMouseDown={() => setDialog(false)}>
          <form
            className="memory-dialog"
            onSubmit={addMemory}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>手动补充</span>
                <h2>补充学习画像</h2>
              </div>
              <button type="button" onClick={() => setDialog(false)}>
                <X size={18} />
              </button>
            </header>
            <label>
              <span>类型</span>
              <select
                value={form.category}
                onChange={(event) =>
                  setForm({ ...form, category: event.target.value })
                }
              >
                <option value="preference">表达偏好</option>
                <option value="weak_point">薄弱点</option>
                <option value="progress">学习进度</option>
              </select>
            </label>
            {form.category === "weak_point" && (
              <label>
                <span>主题</span>
                <input
                  required
                  value={form.topic}
                  onChange={(event) =>
                    setForm({ ...form, topic: event.target.value })
                  }
                  placeholder="例如：梯度下降"
                />
              </label>
            )}
            <label>
              <span>内容</span>
              <textarea
                required
                rows={4}
                value={form.content}
                onChange={(event) =>
                  setForm({ ...form, content: event.target.value })
                }
                placeholder={
                  form.category === "progress"
                    ? "第三章/第二节"
                    : "写下一条真实、具体的信息"
                }
              />
            </label>
            <button className="dialog-submit">
              写入画像
              <ArrowUpRight size={17} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
