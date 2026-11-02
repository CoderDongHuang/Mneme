import { useFormatters } from '../hooks/useFormatters'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import { usePersonalRecovery } from '../features/recovery/usePersonalRecovery'
import { Link } from 'react-router-dom'
import { FeedbackBlock, StatusPill } from '../components/ui'

const labels = { knowledge_bases: '资料库', documents: '原始文件', sessions: '会话', messages: '消息', branches: '分支', plans: '学习计划', reviews: '复习卡', quizzes: '测验', quiz_attempts: '答题记录', learning_outcomes: '学习记录' }
export default function PersonalRecovery() {
  const dates = useDateFormatter()
  const fmt = useFormatters()
  useI18n();
  const { file, fileKey, scope, chooseFile, chooseScope, preview, result, confirmation, setConfirmation, error, busy, step,
    uncertain, verify, confirm, restore, reset, back } = usePersonalRecovery()
  return <section className="recovery-wizard" aria-label={t("个人恢复向导")} aria-busy={!!busy}>
    <ol className="wizard-steps" aria-label={t("恢复进度")}>{[t("选择归档与范围"), t("完整性与冲突预览"), t("确认恢复"), t("验证结果")].map((text, i) => <li key={text} aria-current={step === i + 1 ? 'step' : undefined}><span>{i + 1}</span>{text}</li>)}</ol>
    <FeedbackBlock error={error} />
    {uncertain && <div className="action-row"><Link to="/knowledge">{t("打开文件并验证内容")}</Link><Link to="/chat">{t("验证引用检索")}</Link><button onClick={reset}>{t("已核实结果，重新选择归档")}</button></div>}
    <p>{t("个人恢复为新增副本，保留当前数据。同名资料库也会新建；重复导入会产生重复副本。原始文件恢复后需要重新解析、建立索引。")}</p>
    <p className="muted">{t("包含资料库、原文件、会话、学习计划和测验记录。不包含账户密码、个人模型密钥、偏好和向量记忆；这些数据由管理员整站备份覆盖。")}</p>
    <fieldset disabled={busy === 'restore' || uncertain || step > 2}><legend>{t("选择备份")}</legend><label>{t("个人归档 ZIP（最多 50 MiB）")}<input key={fileKey} type="file" accept=".zip,application/zip" onChange={e => chooseFile(e.target.files?.[0] || null)} /></label><label>{t("恢复范围")}<select aria-label={t("恢复范围")} value={scope} onChange={e => chooseScope(e.target.value)}><option value="all">{t("全部个人归档数据")}</option><option value="knowledge">{t("资料库与原始文件")}</option><option value="conversations">{t("会话、消息与分支")}</option><option value="learning">{t("计划、复习与测验（附带空资料库）")}</option></select></label></fieldset>
    {step < 3 && <button className="primary-button" disabled={!file || !!busy || uncertain} onClick={verify}>{busy === 'preview' ? t("正在校验…") : t("验证清单与文件完整性")}</button>}
    {preview && <section className="restore-preview"><h2>{t("恢复预览")}</h2><StatusPill tone="success">{t("清单及现有文件哈希校验通过")}</StatusPill><dl className="definition-grid"><dt>{t("备份格式")}</dt><dd>Mneme workspace v{preview.version}</dd><dt>{t("创建时间")}</dt><dd>{preview.created_at === 'unknown' ? t("归档未提供") : dates.dateTime(preview.created_at)}</dd><dt>{t("大小 / 加密")}</dt><dd>{fmt.bytes(preview.bytes)} · {preview.encrypted ? t("已加密") : t("未加密")}</dd><dt>{t("兼容性")}</dt><dd>{t("当前服务支持")}</dd><dt>{t("覆盖 / 保留")}</dt><dd>{t("覆盖 0 项，保留全部现有数据")}</dd><dt>SHA-256</dt><dd className="break-word">{preview.sha256}</dd></dl>
      <table><caption>{t("本次新增范围")}</caption><thead><tr><th>{t("数据类型")}</th><th>{t("清单记录数")}</th></tr></thead><tbody>{Object.entries(preview.counts).map(([key, count]) => <tr key={key}><td>{t(labels[key] || key)}</td><td>{fmt.integer(count)}</td></tr>)}</tbody></table>
      {preview.missing_files > 0 && <p role="alert">{t("清单中有 ")}{fmt.integer(preview.missing_files)}{t(" 个原文件缺失，无法恢复这些文件。其他记录可以恢复。")}</p>}
      {preview.same_name_libraries.length > 0 && <p>{t("同名资料库：")}{preview.same_name_libraries.join('、')}{t("。将创建副本，原库保留。")}</p>}
      <p>{t("执行前再次核验同一归档。失败时回滚关系数据并清理本次已恢复文件；索引任务可在任务中心重试。文件已导入不代表检索已经可用。")}</p>
      {step === 2 && <button disabled={!!busy} onClick={confirm}>{t("继续确认")}</button>}
    </section>}
    {step === 3 && <form className="form-stack" onSubmit={e => { e.preventDefault(); void restore() }}><label>{t("输入 RESTORE MY DATA 确认新增副本")}<input disabled={!!busy || uncertain} autoComplete="off" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><div className="action-row"><button type="button" disabled={!!busy || uncertain} onClick={back}>{t("返回预览")}</button><button className="primary-button" disabled={!!busy || uncertain || confirmation !== 'RESTORE MY DATA'}>{busy ? t("正在恢复…") : t("执行个人恢复")}</button></div></form>}
    {result && <section role="status"><h2>{t("恢复结果")}</h2><p>{result.message}</p><dl className="definition-grid"><dt>{t("关系数据")}</dt><dd>{t("事务已提交")}</dd><dt>{t("原文件")}</dt><dd>{t("恢复 ")}{fmt.integer(result.documents.restored)}{t(" 项，跳过 ")}{fmt.integer(result.documents.skipped)}{t(" 项")}</dd><dt>{t("检索索引")}</dt><dd>{t("等待任务完成后验证")}</dd></dl><ul>{Object.entries(result.workspace.counts).map(([key, count]) => <li key={key}>{t(labels[key] || key)}：{fmt.integer(count)}</li>)}</ul><div className="action-row"><Link to="/tasks">{t("检查重建任务")}</Link><Link to="/knowledge">{t("打开文件并验证内容")}</Link><Link to="/chat">{t("验证引用检索")}</Link><button onClick={reset}>{t("恢复其他归档")}</button></div></section>}
  </section>
}
