import license from '../../../LICENSE?raw'

// Published application notices; the MIT text is built from the repository license.
export const legalVersion = '2026.10'
export const legalUpdatedAt = '2026-10-30'
export const legalDocuments = {
  terms: { title: '服务条款', sections: [
    ['scope', '服务范围', '忆知提供文档管理、检索问答和学习辅助，不保证生成内容完全准确，重要结论应核对原文引用。'],
    ['responsibility', '用户责任', '用户不得上传无权处理的资料、恶意文件或利用服务实施违法行为。'],
    ['account', '账号与数据', '用户应妥善保管账号。服务方应提供合理的安全、备份和数据删除能力。'],
  ] },
  privacy: { title: '隐私政策', sections: [
    ['scope', '收集与用途', '忆知处理账号资料、上传文档、会话与学习画像，仅用于提供检索、问答和学习服务。'],
    ['data', '保存与删除', '数据保存在部署方配置的数据库和文件存储中。用户可在隐私中心导出数据或提交账号及关联数据删除任务；后台删除可由管理员追踪。'],
    ['service', '模型服务', '启用外部模型时，问题和必要上下文可能发送至配置的模型提供方，当前个人供应商可在设置中查看。文档向量化、图片理解及后台任务使用部署方配置的服务；个人密钥加密保存，日志不应包含密钥。离线演示仅提供原文摘录，不进行真实模型推理。'],
  ] },
  license: { title: '开源许可', sections: [['license', 'MIT License', license]], verbatim: true },
}
