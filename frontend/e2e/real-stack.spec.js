import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { expect, test } from '@playwright/test'


test.skip(process.env.MNEME_REAL_E2E !== 'true', '仅在完整 Docker 栈中显式运行')
test.setTimeout(180_000)

test('真实注册、资料入库、检索引用和流式回答', async ({ page }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const username = `e2e_${suffix}`
  const password = `Mneme_${suffix}!`
  const imageDirectory = path.resolve('../docs/images')

  await page.goto('/auth')
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-auth.png'), fullPage: true })
  const register = await page.request.post('/api/v1/auth/register', {
    data: { username, password },
  })
  expect(register.ok()).toBeTruthy()
  const session = (await register.json()).data
  await page.addInitScript((value) => {
    localStorage.setItem('mneme_auth', JSON.stringify(value))
  }, session)

  const createKb = await page.request.post('/api/v1/knowledge/base', {
    data: { name: `真实验收-${suffix}`, description: 'Playwright 全链路验收' },
  })
  expect(createKb.ok()).toBeTruthy()
  const kb = (await createKb.json()).data

  const fixture = path.resolve('../test-fixtures/rag-fixture.txt')
  const upload = await page.request.post('/api/v1/knowledge/document/upload', {
    multipart: {
      kbId: String(kb.id),
      file: {
        name: 'rag-fixture.txt',
        mimeType: 'text/plain',
        buffer: fs.readFileSync(fixture),
      },
    },
  })
  expect(upload.ok()).toBeTruthy()
  let document = (await upload.json()).data

  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/knowledge/document/${document.id}/status`)
    document = (await response.json()).data
    return document.status
  }, { timeout: 90_000, intervals: [1000, 2000, 3000] }).toBe('ready')
  expect(document.chunkCount).toBeGreaterThan(0)

  await page.goto('/knowledge')
  await expect(page.getByText('rag-fixture.txt')).toBeVisible()
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-knowledge.png'), fullPage: true })
  await page.goto('/chat')
  await page.getByPlaceholder('向忆知提问...').fill('星桥计划的核心识别码是什么？请引用资料。')
  await page.getByTitle('发送').click()
  await expect(page.locator('.message-assistant')).toContainText('QZ-7294', { timeout: 90_000 })
  await expect(page.getByRole('button', { name: /查看 \d+ 条资料依据/ })).toBeVisible()
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-rag-chat.png'), fullPage: true })
})
