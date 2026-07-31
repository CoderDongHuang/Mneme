import { Link, useParams } from 'react-router-dom'
import '../styles/legal.css'

export default function LegalPage() {
  const { document } = useParams()
  const privacy = document === 'privacy'
  return <main className="legal-page">
    <Link to="/auth">返回忆知</Link>
    <p>{privacy ? '隐私说明' : '服务条款'}</p>
    <h1>{privacy ? '隐私政策' : '服务条款'}</h1>
    {privacy ? <>
      <h2>收集与用途</h2><p>忆知处理账号资料、上传文档、会话与学习画像，仅用于提供检索、问答和学习服务。</p>
      <h2>保存与删除</h2><p>数据保存在部署方配置的数据库和文件存储中。用户可在用户中心删除账号及关联数据。</p>
      <h2>模型服务</h2><p>启用外部模型时，问题和必要上下文可能发送至配置的模型提供方，部署方应在上线前披露具体供应商。</p>
    </> : <>
      <h2>服务范围</h2><p>忆知提供文档管理、检索问答和学习辅助，不保证生成内容完全准确，重要结论应核对原文引用。</p>
      <h2>用户责任</h2><p>用户不得上传无权处理的资料、恶意文件或利用服务实施违法行为。</p>
      <h2>账号与数据</h2><p>用户应妥善保管账号。服务方应提供合理的安全、备份和数据删除能力。</p>
    </>}
  </main>
}
