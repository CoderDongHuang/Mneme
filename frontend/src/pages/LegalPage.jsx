import { t, useI18n } from '../i18n'
import { Link, useParams } from 'react-router-dom'
import '../styles/legal.css'

export default function LegalPage() {
  useI18n();
  const { document } = useParams()
  const privacy = document === 'privacy'
  return <main className="legal-page">
    <Link to="/auth">{t("返回忆知")}</Link>
    <p>{privacy ? t("隐私说明") : t("服务条款")}</p>
    <h1>{privacy ? t("隐私政策") : t("服务条款")}</h1>
    <p className="muted">{t("版本 2026.10 · 更新日期：2026-10-29")}</p><nav aria-label={t("文档目录")}><a href="#scope">{t("范围与用途")}</a><a href="#data">{t("数据与账户")}</a><a href="#service">{t("服务说明")}</a></nav>
    {privacy ? <>
      <h2 id="scope">{t("收集与用途")}</h2><p>{t("忆知处理账号资料、上传文档、会话与学习画像，仅用于提供检索、问答和学习服务。")}</p>
      <h2 id="data">{t("保存与删除")}</h2><p>{t("数据保存在部署方配置的数据库和文件存储中。用户可在隐私中心导出数据或提交账号及关联数据删除任务；后台删除可由管理员追踪。")}</p>
      <h2 id="service">{t("模型服务")}</h2><p>{t("启用外部模型时，问题和必要上下文可能发送至配置的模型提供方，当前个人供应商可在设置中查看。文档向量化、图片理解及后台任务使用部署方配置的服务；个人密钥加密保存，日志不应包含密钥。离线演示仅提供原文摘录，不进行真实模型推理。")}</p>
    </> : <>
      <h2 id="scope">{t("服务范围")}</h2><p>{t("忆知提供文档管理、检索问答和学习辅助，不保证生成内容完全准确，重要结论应核对原文引用。")}</p>
      <h2 id="service">{t("用户责任")}</h2><p>{t("用户不得上传无权处理的资料、恶意文件或利用服务实施违法行为。")}</p>
      <h2 id="data">{t("账号与数据")}</h2><p>{t("用户应妥善保管账号。服务方应提供合理的安全、备份和数据删除能力。")}</p>
    </>}
    <p><Link to="/privacy">{t("管理隐私与数据")}</Link> · <Link to="/settings">{t("查看服务配置")}</Link></p>
  </main>
}
