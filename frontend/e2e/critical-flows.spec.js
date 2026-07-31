import { expect, test } from '@playwright/test'

const ok = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data }) })

test.beforeEach(async ({ page }) => {
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
