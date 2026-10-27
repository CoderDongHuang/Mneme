import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { expect, test } from '@playwright/test'

test.skip(process.env.MNEME_DEMO_E2E !== 'true', '仅在隔离的离线演示栈运行')
test.setTimeout(150_000)

test('无模型密钥的全新演示：账号、解析、原文引用、配置检测', async ({ page, playwright }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  await page.goto('/auth')
  await expect(page.getByText(/离线演示/).first()).toBeVisible()
  const register = await page.request.post('/api/v1/auth/register', {
    data: { username: `demo_${suffix}`, password: `Demo_${suffix}!` },
  })
  expect(register.ok()).toBeTruthy()
  const session = (await register.json()).data
  await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), session)
  const create = await page.request.post('/api/v1/knowledge/base', { data: { name: `Demo-${suffix}` } })
  expect(create.ok()).toBeTruthy()
  const kb = (await create.json()).data
  const upload = await page.request.post('/api/v1/knowledge/document/upload', {
    multipart: { kbId: String(kb.id), file: { name: 'synthetic.txt', mimeType: 'text/plain',
      buffer: fs.readFileSync(path.resolve('../test-fixtures/rag-fixture.txt')) } },
  })
  expect(upload.ok()).toBeTruthy()
  const document = (await upload.json()).data
  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/knowledge/document/${document.id}/status`)
    return (await response.json()).data.status
  }, { timeout: 90_000 }).toBe('ready')
  await page.goto('/chat')
  await page.getByPlaceholder('向忆知提问...').fill('星桥计划的核心识别码是什么？请引用资料。')
  await page.getByTitle('发送').click()
  await expect(page.locator('.message-assistant')).toContainText('原文摘录', { timeout: 45_000 })
  await expect(page.locator('.message-assistant')).toContainText('QZ-7294')
  await expect(page.getByRole('button', { name: /查看 \d+ 条资料依据/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/demo-chat.png', fullPage: true })
  await page.goto('/settings')
  await page.getByRole('button', { name: '检测连通性' }).click()
  await expect(page.getByRole('status').first()).toContainText('连接正常', { timeout: 25_000 })
  await page.screenshot({ path: 'test-results/demo-diagnostics.png', fullPage: true })
  const anonymous = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  expect((await anonymous.post('/api/v1/health/providers/check')).status()).toBe(401)
  await anonymous.dispose()
})
