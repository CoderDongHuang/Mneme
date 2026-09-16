import { Activity, CheckCircle2, CircleAlert, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { endpoints } from "../api/client";
import LoadingState from "../components/LoadingState";
import "../styles/settings.css";

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try { setData(await endpoints.healthConfig()); }
    catch (requestError) { setError(requestError.message); }
  }

  useEffect(() => { load(); }, []);

  const groups = [
    ["模型与解析", data?.configuration || {}],
    ["存储与隔离", { ...(data?.storage || {}), ...(data?.tenant_isolation || {}) }],
    ["密钥与治理", data?.secret_rotation || {}],
  ];
  function label(value) {
    if (typeof value === "boolean") return value ? "已就绪" : "需处理";
    return String(value);
  }
  function warning(value, key) {
    if (key === "browser_secrets_exposed") return value === true;
    if (key.endsWith("_due")) return value === true;
    return value === false;
  }
  return (
    <div className="settings-page">
      <header className="settings-head">
        <div>
          <p className="eyebrow">运行诊断</p>
          <h1>服务配置</h1>
          <p>仅显示配置是否就绪，不会读取或保存任何密钥。</p>
        </div>
        <button onClick={load} title="刷新配置状态"><RefreshCw size={17} />刷新</button>
      </header>
      {error && <div className="page-error">{error}</div>}
      {!data && !error ? <LoadingState label="正在检查服务配置" /> : (
        <section className="config-grid">
          {groups.map(([title, values]) => {
            const entries = Object.entries(values);
            if (!entries.length) return null;
            return (
              <div className="config-group" key={title}>
                <h2>{title}</h2>
                {entries.map(([key, value]) => (
                  <article key={key} className={warning(value, key) ? "config-item warning" : "config-item"}>
                    {warning(value, key) ? <CircleAlert size={20} /> : <CheckCircle2 size={20} />}
                    <div><strong>{key}</strong><span>{label(value)}</span></div>
                  </article>
                ))}
              </div>
            );
          })}
          {!groups.some(([, values]) => Object.keys(values).length) && <div className="settings-empty"><Activity size={28} /><span>暂时无法读取配置状态</span></div>}
        </section>
      )}
    </div>
  );
}
