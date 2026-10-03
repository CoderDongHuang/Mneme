import { expect, test } from '@playwright/test'

const ok = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data }) })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.EventSource = class {
      addEventListener() {}
      close() {}
    }
  })
  await page.addInitScript(() => localStorage.setItem('mneme_auth', JSON.stringify({ userId: 1, username: 'tester', nickname: '测试用户' })))
  await page.route('**/api/v1/profile', route => route.fulfill(ok({ userId: 1, username: 'tester', nickname: '测试用户', email: 'test@example.com', hasAvatar: false })))
  await page.route('**/api/v1/sessions', route => route.fulfill(ok([])))
  await page.route('**/api/v1/knowledge/base/list', route => route.fulfill(ok([{ id: 1, name: '验收资料库' }])))
})

test('头像进入用户中心并显示资料表单', async ({ page }) => {
  await page.goto('/profile')
  await expect(page.getByRole('heading', { name: '管理你的学习身份' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '昵称' })).toHaveValue('测试用户')
  await expect(page.getByRole('textbox', { name: '绑定邮箱' })).toHaveValue('test@example.com')
})

test('聊天输入框适配视口并展示资料范围', async ({ page }) => {
  await page.goto('/chat')
  const composer = page.getByRole('textbox', { name: '向忆知提问...' })
  await expect(composer).toBeVisible()
  await expect(page.locator('.composer-context').getByText('全部资料库')).toBeVisible()
  const box = await composer.boundingBox()
  expect(box.width).toBeGreaterThan(page.viewportSize().width < 500 ? 220 : 600)
})

test('学习画像填满首屏且无横向溢出', async ({ page }) => {
  await page.route('**/api/v1/memory', route => route.fulfill(ok({ preferences: [], weakPoints: [], progress: null })))
  await page.goto('/memory')
  await expect(page.getByRole('heading', { name: '学习画像' })).toBeVisible()
  const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, height: document.querySelector('.memory-page')?.getBoundingClientRect().height }))
  expect(dimensions.scroll).toBe(dimensions.client)
  expect(dimensions.height).toBeGreaterThanOrEqual(page.viewportSize().height - 30)
})

test('文档版本历史可查看且当前版本不可重复恢复', async ({ page }) => {
  await page.route('**/api/v1/knowledge/base/1/documents', route => route.fulfill(ok([
    { id: 9, fileName: 'guide.pdf', status: 'ready', chunkCount: 12, updatedAt: '2026-09-16T10:00:00' },
  ])))
  await page.route('**/api/v1/notifications', route => route.fulfill(ok([])))
  await page.route('**/api/v1/knowledge/document/9/versions', route => route.fulfill(ok([
    { version_number: 2, file_name: 'guide.pdf', sha256: 'abcdef0123456789', active: true, created_at: '2026-09-16T10:00:00' },
    { version_number: 1, file_name: 'guide-old.pdf', sha256: '1234567890abcdef', active: false, created_at: '2026-09-15T10:00:00' },
  ])))
  await page.goto('/knowledge')

  await page.getByTitle('版本历史').click()

  await expect(page.getByRole('heading', { name: 'guide.pdf' })).toBeVisible()
  await expect(page.getByText('v2 · guide.pdf')).toBeVisible()
  await expect(page.getByRole('button', { name: /v2 · guide.pdf/ })).toBeDisabled()
  const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  expect(dimensions.scroll).toBe(dimensions.client)
})

test('学习分析反馈可保存和删除且空数据不伪造', async ({ page }) => {
  let feedback = []
  await page.route('**/api/v1/analytics?days=*', route => route.fulfill(ok({
    topics: [], daily: [], feedback_summary: [], feedback,
    answers: [{ id: 44, excerpt: '可评价的回答' }], trace_quality: { status: 'unavailable' },
  })))
  await page.route('**/api/v1/analytics/feedback', async route => {
    const body = route.request().postDataJSON()
    expect(body.message_id).toBe(44)
    feedback = [{ ...body, id: 7 }]
    await route.fulfill(ok({ status: 'saved' }))
  })
  await page.route('**/api/v1/analytics/feedback/7', async route => {
    expect(route.request().method()).toBe('DELETE')
    feedback = []
    await route.fulfill(ok({ status: 'deleted' }))
  })
  await page.goto('/analytics')
  await expect(page.getByText('Trace 数据源不可用')).toBeVisible()
  await page.getByLabel('回答', { exact: true }).selectOption('44')
  await page.getByLabel('回答评价', { exact: true }).selectOption('refusal')
  await page.getByLabel('原因', { exact: true }).selectOption('no_evidence')
  await page.getByRole('button', { name: '保存反馈' }).click()
  await expect(page.getByText('反馈已保存')).toBeVisible()
  await page.getByTitle('删除反馈 7').click()
  await expect(page.getByText('反馈已删除')).toBeVisible()
  const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  expect(dimensions.scroll).toBe(dimensions.client)
})
