import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('资料与会话故障可重试，撤销成功不因刷新失败被抹去', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180_000)
  page.setDefaultTimeout(15_000)
  const suffix = randomUUID().replaceAll('-', '')
  const username = `profilestate_${suffix.slice(0, 10)}`, password = `States!${suffix}`
  let account, other
  let failProfile = true, failSessions = true, sessionReads = 0
  async function request(client, method, path, data, expected = 200) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const response = await client[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429) {
        await page.waitForTimeout(Math.min(60_000, Math.max(1000, Number(response.headers()['retry-after'] || 5) * 1000)))
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(expected)
      if (expected !== 200) return
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const fits = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  try {
    account = await request(page.request, 'post', '/auth/register', { username, password })
    await page.addInitScript(value => {
      if (!sessionStorage.getItem('profile-states-initialized')) {
        localStorage.setItem('mneme_auth', JSON.stringify(value))
        sessionStorage.setItem('profile-states-initialized', 'true')
      }
    }, account)
    await page.route('**/api/v1/profile', route => route.request().method() === 'GET' && failProfile
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '资料服务暂不可用' }) })
      : route.continue())
    await page.route('**/api/v1/profile/sessions', route => {
      if (route.request().method() !== 'GET') return route.continue()
      sessionReads++
      return failSessions ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '会话服务暂不可用' }) }) : route.continue()
    })
    await page.goto('/profile')
    await expect(page.getByRole('heading', { name: '个人资料', exact: true })).toBeVisible()
    await expect(page.getByText('资料服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText('暂无活动会话。', { exact: true })).toHaveCount(0)
    expect(sessionReads).toBe(0)
    await fits()
    await page.screenshot({ path: testInfo.outputPath('profile-unavailable.png'), fullPage: true })
    failProfile = false
    await page.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(page.getByLabel('昵称', { exact: true })).toBeVisible()
    await page.getByLabel('昵称', { exact: true }).fill('未保存的资料草稿')
    await page.getByRole('button', { name: '账户安全', exact: true }).click()
    const sessions = page.getByRole('region', { name: '登录会话', exact: true })
    await expect(sessions.getByText('登录会话加载失败：会话服务暂不可用', { exact: true })).toBeVisible()
    await expect(sessions.getByText('暂无活动会话。', { exact: true })).toHaveCount(0)
    failSessions = false
    await sessions.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(sessions.getByRole('button', { name: '撤销会话', exact: true })).toHaveCount(1)
    const before = await request(page.request, 'get', '/profile/sessions')
    other = await playwright.request.newContext({ baseURL: testInfo.project.use.baseURL || process.env.MNEME_E2E_BASE_URL })
    await request(other, 'post', '/auth/login', { username, password })
    const after = await request(page.request, 'get', '/profile/sessions')
    const added = after.find(item => !before.some(old => old.session_id === item.session_id))
    expect(added).toBeTruthy()
    // Remount the feature to load both real sessions, preserving the unsaved profile draft.
    await page.getByRole('button', { name: '基本资料', exact: true }).click()
    await expect(page.getByLabel('昵称', { exact: true })).toHaveValue('未保存的资料草稿')
    const listResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/profile/sessions') && response.request().method() === 'GET')
    await page.getByRole('button', { name: '账户安全', exact: true }).click()
    const displayed = (await (await listResponse).json()).data
    await expect(sessions.getByRole('button', { name: '撤销会话', exact: true })).toHaveCount(2)
    const index = displayed.findIndex(item => item.session_id === added.session_id)
    // The API's most-recent-first order is retained by the view.
    failSessions = true
    await sessions.getByRole('button', { name: '撤销会话', exact: true }).nth(index).click()
    await expect(sessions.getByText('会话已撤销', { exact: true })).toBeVisible()
    await expect(sessions.getByText('登录会话加载失败：会话服务暂不可用', { exact: true })).toBeVisible()
    await expect(sessions.getByText('已有会话记录可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(sessions.getByRole('button', { name: '撤销会话', exact: true })).toHaveCount(1)
    await request(other, 'get', '/profile', undefined, 401)
    const current = await request(page.request, 'get', '/profile/sessions')
    expect(current.map(item => item.session_id)).toEqual(before.map(item => item.session_id))
    await fits()
    await page.screenshot({ path: testInfo.outputPath('session-refresh-failed-after-revoke.png'), fullPage: true })
    failSessions = false
    await sessions.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(sessions.getByText('登录会话加载失败：会话服务暂不可用', { exact: true })).toHaveCount(0)
    await expect(sessions.getByRole('button', { name: '撤销会话', exact: true })).toHaveCount(1)
    await fits()
    await page.screenshot({ path: testInfo.outputPath('sessions-recovered.png'), fullPage: true })
  } finally {
    if (account) await request(page.request, 'delete', '/profile/account')
    await other?.dispose()
  }
})
