import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { expect, test } from '@playwright/test'


test.skip(process.env.MNEME_REAL_E2E !== 'true', '仅在完整 Docker 栈中显式运行')
test.setTimeout(180_000)

test('真实注册、资料入库、检索引用和流式回答', async ({ page }) => {
  await page.setViewportSize({ width: 1586, height: 992 })
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const username = `e2e_${suffix}`
  const password = `Mneme_${suffix}!`
  const imageDirectory = path.resolve(process.env.MNEME_E2E_IMAGE_DIRECTORY || '../artifacts/real-stack-images')
  fs.mkdirSync(imageDirectory, { recursive: true })

  await page.goto('/auth')
  await expect(page.getByRole('heading', { name: '继续你的学习轨迹' })).toBeVisible()
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-auth.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('tab', { name: '注册', exact: true }).click()
  await page.getByPlaceholder('输入用户名', { exact: true }).fill(username)
  await page.getByPlaceholder('至少 8 个字符', { exact: true }).fill(password)
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await expect(page).toHaveURL(/\/chat/)
  await page.request.post('/api/v1/auth/logout')
  await page.evaluate(() => localStorage.removeItem('mneme_auth'))
  await page.goto('/auth')
  await page.getByPlaceholder('输入用户名', { exact: true }).fill(username)
  await page.getByPlaceholder('至少 8 个字符', { exact: true }).fill(`${password}wrong`)
  await page.getByRole('button', { name: '进入忆知', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByPlaceholder('至少 8 个字符', { exact: true }).fill(password)
  await page.getByRole('button', { name: '进入忆知', exact: true }).click()
  await expect(page).toHaveURL(/\/chat/)

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
  await expect(page.getByRole('button', { name: 'rag-fixture.txt', exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-knowledge.png'), fullPage: true, animations: 'disabled' })
  await page.goto('/chat')
  await page.getByPlaceholder('向忆知提问...').fill('星桥计划的核心识别码是什么？请引用资料。')
  await page.getByTitle('发送').click()
  await expect(page.locator('.message-assistant')).toContainText('QZ-7294', { timeout: 90_000 })
  await expect(page.getByRole('button', { name: /查看 \d+ 条资料依据/ })).toBeVisible()
  await expect(page.locator('.source-drawer article strong').first()).toHaveText('rag-fixture.txt')

  await page.getByPlaceholder('向忆知提问...').fill('请结合上一轮，再用一句话确认识别码。')
  await page.getByTitle('发送').click()
  await expect(page.locator('.message-assistant')).toHaveCount(2, { timeout: 90_000 })
  await expect(page.locator('.message-assistant').last()).toContainText('QZ-7294', { timeout: 90_000 })
  await expect(page.getByTitle('发送')).toBeVisible({ timeout: 90_000 })
  await page.reload()
  const historyToggle = page.getByRole('button', { name: '切换会话栏' })
  if (await historyToggle.getAttribute('aria-expanded') === 'false') await historyToggle.click()
  await page.getByRole('button', { name: /^打开对话：/ }).first().click()
  await expect(page.locator('.message-assistant')).toHaveCount(2, { timeout: 30_000 })
  const restoredAnswer = page.locator('.message-assistant').last()
  await expect(restoredAnswer).toContainText('QZ-7294')
  await restoredAnswer.scrollIntoViewIfNeeded()
  await expect(restoredAnswer).toBeInViewport()
  await page.screenshot({ path: path.join(imageDirectory, 'mneme-rag-chat.png'), fullPage: true, animations: 'disabled' })
  for (const width of [816, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(restoredAnswer).toContainText('QZ-7294')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: path.join(imageDirectory, `mneme-rag-chat-${width}.png`), fullPage: true, animations: 'disabled' })
    await page.getByRole('button', { name: /查看 \d+ 条资料依据/ }).last().click()
    await expect(page.getByRole('dialog', { name: '引用与原文', exact: true })).toBeVisible()
    await page.screenshot({ path: path.join(imageDirectory, `mneme-citations-${width}.png`), fullPage: true, animations: 'disabled' })
    await page.getByRole('button', { name: '关闭资料依据' }).click()
  }
})
