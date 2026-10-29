import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.setTimeout(900_000)
async function data(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  const body = await response.json()
  expect(body.code ?? 200).toBe(200)
  return body.data ?? body
}
async function register(page) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const auth = await data(await page.request.post('/api/v1/auth/register', { data: { username: `review_${suffix}`, password: `Mneme_${suffix}!` } }))
  await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
  return auth
}

test('个人配置隔离、双语持久化与真实个人归档恢复向导', async ({ page, playwright }) => {
  page.setDefaultTimeout(10_000)
  await register(page)
  await page.goto('/settings')
  const key = 'report-private-key-never-returned'
  await page.getByLabel('API 密钥', { exact: true }).fill(key)
  await page.getByRole('button', { name: '保存配置', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '模型配置已保存' })).toBeVisible()
  const config = await data(await page.request.get('/api/v1/settings/models'))
  expect(config.hasKey).toBe(true)
  expect(JSON.stringify(config)).not.toContain(key)
  await page.reload()
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  await data(await other.post('/api/v1/auth/register', { data: { username: `isolated_${Date.now()}`, password: 'Mneme_123456!' } }))
  expect((await data(await other.get('/api/v1/settings/models'))).hasKey).toBe(false)
  expect((await other.get('/api/v1/admin/recovery/site')).status()).toBe(403)
  await other.dispose()
  await page.goto('/profile')
  await page.getByLabel('界面语言').selectOption('en')
  await page.getByLabel('时区', { exact: true }).selectOption('UTC')
  await page.getByLabel('启用应用通知').uncheck()
  await page.getByRole('button', { name: '保存偏好' }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Language and preferences' })).toBeVisible()
  expect(await data(await page.request.get('/api/v1/settings/preferences'))).toMatchObject({ language: 'en', timezone: 'UTC', notifications: false })
  await data(await page.request.put('/api/v1/settings/preferences', { data: { language: 'zh-CN', timezone: 'Asia/Shanghai', notifications: true, theme: 'light' } }))
  const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: '归档恢复验收' } }))
  await data(await page.request.post('/api/v1/workspace/plans', { data: { title: '恢复卡片', goal: '验证个人数据', cards: [{ prompt: '恢复问题', answer: '恢复答案' }] } }))
  const archive = await page.request.get('/api/v1/workspace/export/archive')
  expect(archive.ok()).toBeTruthy()
  await page.goto('/recovery')
  await page.getByLabel('个人归档 ZIP（最多 50 MB）').setInputFiles({ name: 'workspace.zip', mimeType: 'application/zip', buffer: await archive.body() })
  await page.getByRole('button', { name: '验证清单与文件完整性' }).click()
  await expect(page.getByRole('heading', { name: '恢复预览' })).toBeVisible()
  await expect(page.getByText('同名资料库：')).toContainText('归档恢复验收')
  await page.getByRole('button', { name: '继续确认' }).click()
  await page.getByLabel('输入 RESTORE MY DATA 确认新增副本').fill('RESTORE MY DATA')
  await page.getByRole('button', { name: '执行个人恢复', exact: true }).click()
  await expect(page.getByRole('heading', { name: '恢复结果' })).toBeVisible()
  const bases = await data(await page.request.get('/api/v1/knowledge/base/list'))
  expect(bases.filter(item => item.name === kb.name)).toHaveLength(2)
  expect((await data(await page.request.get('/api/v1/workspace/reviews'))).filter(item => item.prompt === '恢复问题')).toHaveLength(2)
})

test('全部页面在五种宽度与明暗主题下可读，英文导航和页面无横向溢出', async ({ page }) => {
  page.setDefaultTimeout(10_000)
  // Keep real requests below the production IP limit while traversing 240 views.
  let nextRequest = 0
  await page.route('**/api/v1/**', async route => {
    const at = Math.max(Date.now(), nextRequest)
    nextRequest = at + 350
    await new Promise(resolve => setTimeout(resolve, at - Date.now()))
    await route.continue()
  })
  await register(page)
  const directory = path.resolve('../artifacts/frontend-review-20261029/responsive')
  fs.mkdirSync(directory, { recursive: true })
  const routes = ['chat', 'knowledge', 'memory', 'review', 'quiz', 'workspace', 'tasks', 'settings', 'privacy', 'recovery', 'analytics', 'profile']
  for (const language of ['zh-CN', 'en']) {
    for (const theme of ['light', 'dark']) {
      await data(await page.request.put('/api/v1/settings/preferences', { data: { language, timezone: 'UTC', theme, notifications: true } }))
      await page.goto('/chat')
      for (const width of [320, 375, 760, 1024, 1440]) {
        await page.setViewportSize({ width, height: 900 })
        for (const route of routes) {
          if (new URL(page.url()).pathname !== `/${route}`) {
            if (width <= 760) await page.locator('.mobile-nav-toggle').click()
            if (route === 'profile') await page.locator('.profile-entry').click()
            else await page.locator(`#global-navigation nav a[href="/${route}"]`).click()
          }
          await expect(page.locator('html')).toHaveAttribute('lang', language)
          await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
          await expect(page.locator('#main-content')).toBeVisible()
          await expect(page.locator('#main-content h1'), `${language}/${theme}/${width}/${route}`).toBeVisible({ timeout: 30_000 })
          await expect(page.locator('#main-content .loading-state')).toHaveCount(0, { timeout: 30_000 })
          if (route === 'settings') await expect(page.locator('.settings-content .form-stack')).toBeVisible({ timeout: 30_000 })
          if (route === 'review') await expect(page.getByRole('status').filter({ hasText: /正在读取复习卡|Loading review cards/ })).toHaveCount(0, { timeout: 30_000 })
          if (route === 'analytics') await expect(page.getByRole('status').filter({ hasText: /加载中|Loading/ })).toHaveCount(0, { timeout: 30_000 })
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${language}/${theme}/${width}/${route}`).toBeTruthy()
          if (language === 'zh-CN' && [375, 1440].includes(width)) await page.screenshot({ path: path.join(directory, `${route}-${theme}-${width}.png`), fullPage: true, animations: 'disabled' })
        }
      }
    }
  }
})

test('真实复习与测验保留草稿和评分，认证及法律页可访问', async ({ page }) => {
  const directory = path.resolve('../artifacts/frontend-review-20261029/populated')
  fs.mkdirSync(directory, { recursive: true })
  await page.goto('/auth')
  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({ path: path.join(directory, `auth-${width}.png`), fullPage: true })
    expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
  }
  await register(page)
  await data(await page.request.post('/api/v1/workspace/plans', { data: { title: '星桥计划学习', goal: '理解识别码与资料引用', cards: [{ prompt: '星桥计划的识别码是什么？', answer: 'QZ-7294，应结合原文核验。' }] } }))
  await page.goto('/review')
  await expect(page.getByRole('heading', { name: '星桥计划的识别码是什么？' })).toBeVisible()
  await page.getByRole('button', { name: '查看答案', exact: true }).click()
  await expect(page.locator('.answer-panel')).toContainText('QZ-7294')
  await page.screenshot({ path: path.join(directory, 'review.png'), fullPage: true })
  await page.getByRole('button', { name: '基本掌握' }).click()
  await expect(page.getByRole('status').filter({ hasText: '评分已保存' })).toBeVisible()
  expect((await data(await page.request.get('/api/v1/workspace/reviews')))[0].review_count).toBe(1)
  const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: '学习与引用验收' } }))
  const document = await data(await page.request.post('/api/v1/knowledge/document/upload', { multipart: { kbId: String(kb.id), file: { name: 'rag-fixture.txt', mimeType: 'text/plain', buffer: fs.readFileSync(path.resolve('../test-fixtures/rag-fixture.txt')) } } }))
  await expect.poll(async () => (await data(await page.request.get(`/api/v1/knowledge/document/${document.id}/status`))).status, { timeout: 120_000, intervals: [2000] }).toBe('ready')
  const quiz = await data(await page.request.post('/api/v1/workspace/quizzes/generate', { data: { kb_id: kb.id, topic: '星桥计划' }, timeout: 120_000 }))
  const questions = JSON.parse(quiz.questions_json)
  expect(questions.length).toBeGreaterThan(0)
  expect(questions[0]).not.toHaveProperty('answer')
  await page.goto('/quiz')
  await page.locator('.section-nav button').filter({ hasText: quiz.title }).click()
  await expect(page.locator('.study-card h2')).toHaveText(questions[0].prompt)
  if (questions[0].type === 'choice') await page.locator('.quiz-options input').first().check()
  else await page.locator('.study-card textarea').fill('QZ-7294')
  await expect(page.getByRole('status').filter({ hasText: '草稿已保存' })).toBeVisible()
  await page.reload()
  await page.locator('.section-nav button').filter({ hasText: quiz.title }).click()
  if (questions[0].type === 'choice') await expect(page.locator('.quiz-options input').first()).toBeChecked()
  else await expect(page.locator('.study-card textarea')).toHaveValue('QZ-7294')
  await page.screenshot({ path: path.join(directory, 'quiz.png'), fullPage: true })
  for (const route of ['knowledge', 'tasks', 'analytics', 'profile', 'legal/privacy', 'legal/terms']) {
    await page.goto(`/${route}`)
    await expect(page.locator('h1')).toBeVisible()
    await expect(page.locator('.loading-state')).toHaveCount(0)
    await page.screenshot({ path: path.join(directory, `${route.replace('/', '-')}.png`), fullPage: true })
  }
})
