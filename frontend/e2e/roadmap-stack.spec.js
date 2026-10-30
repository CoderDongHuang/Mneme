import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { Buffer } from 'node:buffer'
import { expect, test } from '@playwright/test'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要实际运行的完整服务')
test.setTimeout(300_000)

async function data(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  const body = await response.json()
  expect(body.code ?? 200).toBe(200)
  return body.data ?? body
}

async function ready(request, id) {
  let doc
  await expect.poll(async () => {
    doc = await data(await request.get(`/api/v1/knowledge/document/${id}/status`))
    return doc.status
  }, { timeout: 150_000, intervals: [500, 1000, 2000] }).toMatch(/^(ready|partial)$/)
  expect(doc.chunkCount).toBeGreaterThan(0)
  return doc
}

test('真实资料闭环：多格式、联合过滤、历史版本、权限、学习与删除', async ({ page, playwright }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const auth = await data(await page.request.post('/api/v1/auth/register', {
    data: { username: `roadmap_${suffix}`, password: `Mneme_${suffix}!` },
  }))
  await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
  const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: `路线图-${suffix}` } }))
  const docs = []
  for (const extension of ['txt', 'md', 'pdf', 'docx', 'pptx', 'xlsx', 'csv', 'html']) {
    const name = `rag-fixture.${extension}`
    const doc = await data(await page.request.post('/api/v1/knowledge/document/upload', {
      multipart: { kbId: String(kb.id), file: { name, mimeType: 'application/octet-stream',
        buffer: fs.readFileSync(path.resolve('../test-fixtures', name)) } },
    }))
    docs.push(await ready(page.request, doc.id))
  }
  const doc = docs[0]
  await data(await page.request.put(`/api/v1/workspace/documents/${doc.id}/tags`, { data: ['课程', '重点'] }))
  expect(await data(await page.request.get(`/api/v1/workspace/documents/${doc.id}/tags`))).toEqual(['课程', '重点'])
  const base = `/api/v1/workspace/retrieval/debug?kbId=${kb.id}&query=${encodeURIComponent('QZ-7294')}&topK=8`
  const today = new Date().toISOString().slice(0, 10)
  const filtered = await data(await page.request.get(`${base}&documentIds=${doc.id}&tags=${encodeURIComponent('课程')}&tags=${encodeURIComponent('重点')}&dateFrom=${today}&dateTo=${today}`))
  expect(filtered.chunks.length).toBeGreaterThan(0)
  expect(filtered.chunks.every(chunk => chunk.metadata.document_id === `doc_${doc.id}`)).toBeTruthy()
  expect(Object.keys(filtered.chunks[0].retrieval_ranks).length).toBeGreaterThan(0)
  for (const query of ['tags=missing', 'dateTo=2000-01-01', `documentIds=${docs[1].id}&tags=${encodeURIComponent('重点')}`]) {
    expect((await data(await page.request.get(`${base}&${query}`))).chunks).toEqual([])
  }
  expect((await page.request.get(`${base}&dateFrom=bad`)).status()).toBe(400)

  const versions = await data(await page.request.get(`/api/v1/knowledge/document/${doc.id}/versions`))
  const hash = versions[0].sha256
  const original = await data(await page.request.get(`/api/v1/workspace/documents/${doc.id}/preview?sha256=${hash}`))
  expect(original.content).toContain('QZ-7294')
  expect(original.parse_report.chunks.length).toBeGreaterThan(0)
  expect(original.parse_report.parser_version).toBe('mneme-structured-v3')
  await data(await page.request.post(`/api/v1/knowledge/document/${doc.id}/replace`, {
    multipart: { file: { name: 'revised.txt', mimeType: 'text/plain', buffer: Buffer.from('The revised release identifier is NEW-8421. This version replaces the original record.') } },
  }))
  await ready(page.request, doc.id)
  const historical = await data(await page.request.get(`/api/v1/workspace/documents/${doc.id}/preview?sha256=${hash}`))
  expect(historical.content).toContain('QZ-7294')
  expect(historical.content).not.toContain('NEW-8421')
  expect((await data(await page.request.get(`/api/v1/workspace/documents/${doc.id}/preview`))).content).toContain('NEW-8421')
  expect((await page.request.get(`/api/v1/workspace/documents/${doc.id}/file?sha256=${'f'.repeat(64)}`)).status()).toBe(400)
  await data(await page.request.post(`/api/v1/knowledge/document/${doc.id}/versions/1/restore`))
  await ready(page.request, doc.id)

  const pdf = docs[2]
  const preview = await data(await page.request.get(`/api/v1/workspace/documents/${pdf.id}/preview`))
  expect(preview.parse_report.pages.length).toBeGreaterThan(0)
  const png = await page.request.get(`/api/v1/workspace/documents/${pdf.id}/pages/1`)
  expect(png.ok()).toBeTruthy()
  expect((await png.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  await data(await other.post('/api/v1/auth/register', { data: { username: `isolated_${suffix}`, password: `Mneme_${suffix}!` } }))
  for (const url of [`/workspace/documents/${doc.id}/preview?sha256=${hash}`, `/workspace/documents/${doc.id}/tags`, `/workspace/documents/${pdf.id}/pages/1`, `/knowledge/document/${doc.id}/versions`]) {
    expect((await other.get(`/api/v1${url}`)).status()).toBe(400)
  }
  expect((await other.get(base)).status()).toBe(400)
  await other.dispose()

  const plan = await data(await page.request.post('/api/v1/workspace/plans', { data: { title: '复习计划', goal: '核对资料来源', cards: [{ prompt: '核心识别码是什么？', answer: 'QZ-7294' }] } }))
  const reviews = await data(await page.request.get('/api/v1/workspace/reviews'))
  const card = reviews.find(card => String(card.plan_id) === String(plan.id))
  const reviewed = await data(await page.request.post(`/api/v1/workspace/reviews/${card.id}`, { data: { rating: 4 } }))
  expect(reviewed.review_count).toBe(1)
  const quiz = await data(await page.request.post('/api/v1/workspace/quizzes/generate', { data: { kb_id: kb.id, topic: '星桥计划' }, timeout: 120_000 }))
  const questions = typeof quiz.questions_json === 'string' ? JSON.parse(quiz.questions_json) : quiz.questions_json
  expect(questions.length).toBeGreaterThan(0)
  expect(questions.every(question => !('answer' in question) && !('evidence' in question) && !('key_points' in question))).toBeTruthy()
  const request_id = `roadmap-${suffix}`
  const answers = questions.map(() => '')
  const result = await data(await page.request.post(`/api/v1/workspace/quizzes/${quiz.id}/submit`, { data: { answers, request_id } }))
  expect(result.raw_score).toBe(0)
  expect(result.feedback.every(item => item.expected && item.evidence && item.source)).toBeTruthy()
  expect(await data(await page.request.post(`/api/v1/workspace/quizzes/${quiz.id}/submit`, { data: { answers, request_id } }))).toEqual(result)
  expect(await data(await page.request.get(`/api/v1/workspace/quizzes/${quiz.id}/attempts`))).toHaveLength(1)
  const exported = await data(await page.request.get('/api/v1/workspace/export'))
  expect(exported.reviews.some(item => String(item.id) === String(card.id) && item.review_count === 1)).toBeTruthy()
  expect((await page.request.get('/api/v1/workspace/export/archive')).ok()).toBeTruthy()

  for (const route of ['/chat', '/knowledge', '/workspace', '/tasks', '/memory', '/review', '/quiz', '/recovery', '/privacy', '/analytics', '/profile', '/settings']) {
    await page.goto(route)
    await expect(page).toHaveURL(new RegExp(`${route}$`))
    await expect(page.locator('#main-content')).toBeVisible()
    expect(await page.locator('body').evaluate(body => body.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
  }
  await page.goto('/workspace')
  await page.getByRole('button', { name: '工具', exact: true }).click()
  await page.getByRole('button', { name: '引用阅读', exact: true }).click()
  for (const name of ['引用阅读', '检索调试', '分支对比']) {
    await page.getByRole('button', { name, exact: true }).click()
    await expect(page.getByRole('button', { name, exact: true })).toHaveClass(/active/)
  }
  await data(await page.request.delete(`/api/v1/knowledge/document/${doc.id}`))
  await expect.poll(async () => (await page.request.get(`/api/v1/workspace/documents/${doc.id}/preview?sha256=${hash}`)).status(), { timeout: 30_000 }).toBe(400)
  expect((await data(await page.request.get(`${base}&documentIds=${doc.id}`))).chunks).toEqual([])
  await data(await page.request.delete(`/api/v1/knowledge/base/${kb.id}`))
  for (const url of [`/workspace/documents/${pdf.id}/preview`, `/workspace/documents/${pdf.id}/file`, `/workspace/documents/${pdf.id}/pages/1`]) {
    expect((await page.request.get(`/api/v1${url}`)).status()).toBe(400)
  }
})

test('真实解析异常与恢复：扫描 OCR、复杂布局、损坏文件、运行中取消及重试', async ({ page }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const auth = await data(await page.request.post('/api/v1/auth/register', {
    data: { username: `parsing_${suffix}`, password: `Mneme_${suffix}!` },
  }))
  await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
  const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: `解析-${suffix}` } }))
  async function upload(name, buffer) {
    return data(await page.request.post('/api/v1/knowledge/document/upload', {
      multipart: { kbId: String(kb.id), file: { name, mimeType: 'application/pdf', buffer } },
    }))
  }
  const scan = await upload('scanned-acceptance.pdf', fs.readFileSync(path.resolve('../test-fixtures/scanned-acceptance.pdf')))
  await ready(page.request, scan.id)
  const preview = await data(await page.request.get(`/api/v1/workspace/documents/${scan.id}/preview`))
  expect(preview.parse_report.pages[0].ocr_regions.length).toBeGreaterThan(0)
  expect(preview.parse_report.pages[0].ocr_regions.every(region => region.confidence >= 0 && region.confidence <= 1)).toBeTruthy()
  expect(preview.parse_report.pages[0].text).toContain('SCAN-ALPHA')
  expect(preview.parse_report.pages[0].text).toContain('42 months')
  const complex = await upload('complex-layout.pdf', fs.readFileSync(path.resolve('../python-agent/evaluation/fixtures/complex-layout.pdf')))
  await ready(page.request, complex.id)
  const layout = await data(await page.request.get(`/api/v1/workspace/documents/${complex.id}/preview`))
  expect(layout.parse_report.pages.length).toBeGreaterThan(1)
  expect(layout.parse_report.pages.some(page => page.blocks.some(block => block.type === 'table'))).toBeTruthy()
  const damaged = await upload('damaged.pdf', Buffer.from('%PDF-1.7\nnot a valid cross-reference table'))
  let failure
  await expect.poll(async () => {
    failure = await data(await page.request.get(`/api/v1/knowledge/document/${damaged.id}/status`))
    return failure.status
  }, { timeout: 150_000, intervals: [1000, 2000] }).toBe('failed')
  expect(failure.errorMessage).toBeTruthy()
  const long = await upload('scanned-cancellation.pdf', fs.readFileSync(path.resolve('../test-fixtures/scanned-cancellation.pdf')))
  let task
  await expect.poll(async () => {
    const tasks = await data(await page.request.get('/api/v1/workspace/tasks'))
    task = tasks.find(task => String(task.aggregate_id) === String(long.id) && task.task_type === 'document_ingest')
    return task?.status
  }, { timeout: 30_000, intervals: [100, 200] }).toBe('processing')
  await data(await page.request.post(`/api/v1/workspace/tasks/${task.task_id}/cancel`))
  await expect.poll(async () => {
    const tasks = await data(await page.request.get('/api/v1/workspace/tasks'))
    return tasks.find(item => item.task_id === task.task_id)?.status
  }, { timeout: 60_000, intervals: [500, 1000] }).toBe('cancelled')
  const retry = await data(await page.request.post(`/api/v1/workspace/tasks/${task.task_id}/retry`))
  expect(retry.task_id).not.toBe(task.task_id)
  await ready(page.request, long.id)
  const chunks = await data(await page.request.get(`/api/v1/workspace/retrieval/debug?kbId=${kb.id}&documentIds=${long.id}&query=SCAN-ALPHA&topK=20`))
  expect(chunks.chunks.length).toBeGreaterThan(0)
  expect(new Set(chunks.chunks.map(chunk => chunk.id)).size).toBe(chunks.chunks.length)
  await page.goto('/workspace')
  await page.getByRole('button', { name: '工具', exact: true }).click()
  await page.getByRole('button', { name: '引用阅读', exact: true }).click()
  await page.getByRole('button', { name: 'scanned-acceptance.pdf', exact: false }).click()
  await page.getByText('解析内容 ·', { exact: false }).click()
  await expect(page.getByRole('img', { name: '第 1 页 OCR 区域预览' })).toBeVisible()
  const image = page.getByRole('img', { name: '第 1 页 OCR 区域预览' })
  await expect.poll(() => image.evaluate(img => img.naturalWidth)).toBeGreaterThan(0)
})

test('真实界面交互：标签、筛选、空结果、切换知识库与配置诊断', async ({ page }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const auth = await data(await page.request.post('/api/v1/auth/register', {
    data: { username: `filters_${suffix}`, password: `Mneme_${suffix}!` },
  }))
  await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
  const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: `界面-${suffix}` } }))
  const empty = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: `空库-${suffix}` } }))
  const doc = await data(await page.request.post('/api/v1/knowledge/document/upload', {
    multipart: { kbId: String(kb.id), file: { name: 'rag-fixture.txt', mimeType: 'text/plain',
      buffer: fs.readFileSync(path.resolve('../test-fixtures/rag-fixture.txt')) } },
  }))
  await ready(page.request, doc.id)
  await page.goto(`/workspace?document=${doc.id}`)
  await page.getByLabel('资料标签', { exact: true }).fill('课程,重点')
  await page.getByRole('button', { name: '保存标签', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '标签已保存' })).toBeVisible()
  await page.getByRole('button', { name: '检索调试', exact: true }).click()
  await page.locator('.debugger form > select').selectOption(String(kb.id))
  await page.getByRole('dialog').locator('.retrieval-filters summary').click()
  await page.getByRole('dialog').getByLabel('指定文档（可多选）').selectOption(String(doc.id))
  await page.getByRole('dialog').getByLabel('标签（逗号分隔，同时满足）').fill('课程,重点')
  await page.getByPlaceholder('输入检索问题').fill('QZ-7294')
  const retrieval = page.waitForResponse(response => response.url().includes('/workspace/retrieval/debug') && response.request().method() === 'GET', { timeout: 60_000 })
  await page.getByRole('button', { name: '运行检索', exact: true }).click()
  expect((await data(await retrieval)).chunks.length).toBeGreaterThan(0)
  await expect(page.locator('.retrieval-results article').first()).toContainText('QZ-7294')
  await page.getByRole('dialog').getByLabel('标签（逗号分隔，同时满足）').fill('不存在')
  await page.getByRole('button', { name: '运行检索', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '当前筛选范围没有命中资料' })).toBeVisible()
  await page.locator('.debugger form > select').selectOption(String(empty.id))
  await page.getByRole('dialog').locator('.retrieval-filters summary').click()
  await expect(page.getByRole('dialog').getByLabel('标签（逗号分隔，同时满足）')).toHaveValue('')
  await expect(page.locator('.retrieval-results article')).toHaveCount(0)
  await page.goto('/operations')
  await expect(page.getByRole('heading', { name: '无访问权限' })).toBeVisible()
  expect((await page.request.get('/api/v1/admin/operations')).status()).toBe(403)
  await page.goto('/settings')
  const probe = await data(await page.request.post('/api/v1/health/providers/check', { timeout: 120_000 }))
  expect(Object.keys(probe.results).sort()).toEqual(['chat', 'embedding', 'ocr', 'rerank'])
  await expect(page.getByRole('heading', { name: '个人模型服务' })).toBeVisible()
  expect(await page.locator('body').evaluate(body => body.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
})
