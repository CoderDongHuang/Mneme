import { Activity, CheckCircle2, CircleAlert, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { endpoints } from "../api/client";
import LoadingState from "../components/LoadingState";
import "../styles/settings.css";

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [probe, setProbe] = useState(null);
  const [checking, setChecking] = useState(false);

  async function check() {
    setChecking(true); setError("");
    try { setProbe(await endpoints.checkProviders()); }
    catch (requestError) { setError(requestError.message); }
    finally { setChecking(false); }
  }

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
    if (typeof value === "boolean") return value ? "是" : "否";
    if (value && typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${label(item)}`).join(" · ");
    return value == null ? "未设置" : String(value);
  }
  function warning(value, key) {
    if (key === "browser_secrets_exposed") return value === true;
    if (key.endsWith("_due")) return value === true;
    return ["llm_api_key", "embedding_api_key", "redis_configured", "agent_trace_redaction"].includes(key) && value === false && !data?.demo_mode;
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
      {data?.demo_mode && <p className="provider-notice">当前为离线演示：只检索和摘录原文，推理、自动记忆与 AI 测验需配置真实模型。</p>}
      {data?.provider_profiles && <section className="provider-panel">
        <div className="provider-head"><div><h2>模型与解析服务</h2><p>点击后发送固定合成内容，可能产生少量模型费用；结果缓存 60 秒。</p></div>
          <button onClick={check} disabled={checking}>{checking ? "检测中…" : "检测连通性"}</button></div>
        <div className="provider-grid">{Object.entries(data.provider_profiles).map(([name, profile]) => {
          const result = probe?.results?.[name];
          const states = { ok: "连接正常", disabled: "未启用", model_not_loaded: "本地模型尚未加载，请先完成模型部署", missing_credentials: "缺少服务端密钥", timeout: "连接超时，请检查网络后重试", authentication_failed: "密钥无效或无访问权限", quota_or_rate_limit: "额度不足或触发限流", model_unsupported: "模型不存在或当前账号不支持", runtime_missing: "运行环境或 OCR 语言包缺失", provider_or_network_error: "供应商或网络异常，请检查服务端诊断" };
          return <article className="provider-card" key={name}><h3>{{chat: "对话", embedding: "向量索引", rerank: "检索重排", ocr: "本地 OCR"}[name] || name}</h3>
            <p>{profile.provider}</p><strong>{profile.model}</strong>
            <p>超时 {profile.timeout_seconds} 秒 · 重试上限 {profile.max_retries} 次</p>
            {profile.fallback && <p>备用：{profile.fallback}</p>}
            {profile.enabled === false && <p>当前未启用</p>}
            {result && <p role="status" className={result.state === "ok" ? "probe-ok" : "probe-detail"}>{states[result.state] || "检测异常"} · {result.latency_ms} ms</p>}
          </article>;
        })}</div>
        <p>切换 Embedding 模型需要备份并重建索引；系统会拒绝混用不同向量空间。密钥仅由服务端环境配置。</p>
      </section>}
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
