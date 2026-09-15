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

  const entries = Object.entries(data?.configuration || {});
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
          {entries.map(([key, value]) => (
            <article key={key} className={value === false ? "config-item warning" : "config-item"}>
              {value === false ? <CircleAlert size={20} /> : <CheckCircle2 size={20} />}
              <div><strong>{key}</strong><span>{typeof value === "boolean" ? (value ? "已配置" : "未配置") : String(value)}</span></div>
            </article>
          ))}
          {!entries.length && <div className="settings-empty"><Activity size={28} /><span>暂时无法读取配置状态</span></div>}
        </section>
      )}
    </div>
  );
}
