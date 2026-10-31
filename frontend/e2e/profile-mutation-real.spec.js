import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway 和 MySQL')
// Credentials and authenticated cookies must never enter traces or recordings.
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实头像与资料持久保存，改密撤销所有旧会话且新密码可登录', async ({ page, playwright }, testInfo) => {
  test.setTimeout(240_000)
  page.setDefaultTimeout(15_000)
  const suffix = randomUUID().replaceAll('-', '')
  const username = `profileqa_${suffix.slice(0, 12)}`
  const password = `Initial!${suffix}`, nextPassword = `Changed!${suffix}`
  let account, previousSession
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
  try {
    account = await request(page.request, 'post', '/auth/register', { username, password })
    previousSession = await playwright.request.newContext({
      baseURL: testInfo.project.use.baseURL || process.env.MNEME_E2E_BASE_URL,
      storageState: await page.context().storageState(),
    })
    await request(previousSession, 'post', '/auth/login', { username, password })
    await page.addInitScript(value => {
      if (!sessionStorage.getItem('profile-qa-initialized')) {
        localStorage.setItem('mneme_auth', JSON.stringify(value))
        sessionStorage.setItem('profile-qa-initialized', 'true')
      }
    }, account)
    await page.goto('/profile')
    await expect(page.getByLabel('昵称', { exact: true })).toBeVisible()
    const avatar = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=', 'base64')
    await page.locator('input[type=file]').setInputFiles({ name: 'profile-avatar.png', mimeType: 'image/png', buffer: avatar })
    await expect(page.getByText('头像已更新', { exact: true })).toBeVisible()
    const image = await page.request.get('/api/v1/profile/avatar')
    expect(image.status()).toBe(200)
    expect(await image.body()).toEqual(avatar)
    await page.getByLabel('昵称', { exact: true }).fill('资料持久化验证')
    await page.getByLabel('绑定邮箱', { exact: true }).fill(`${username}@example.test`)
    await page.getByRole('button', { name: '保存资料', exact: true }).click()
    await expect(page.getByText('个人资料已保存', { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByLabel('昵称', { exact: true })).toHaveValue('资料持久化验证')
    await expect(page.getByAltText('当前头像')).toBeVisible()
    await page.getByRole('button', { name: '账户安全', exact: true }).click()
    await page.getByLabel('当前密码', { exact: true }).fill(password)
    await page.getByLabel('新密码', { exact: true }).fill(nextPassword)
    await page.getByLabel('确认新密码', { exact: true }).fill(nextPassword)
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/v1/auth/logout')),
      page.getByRole('button', { name: '确认修改', exact: true }).click(),
    ])
    await expect(page).toHaveURL(/\/auth$/)
    await request(previousSession, 'get', '/profile', undefined, 401)
    await request(page.request, 'get', '/profile', undefined, 401)
    await request(page.request, 'post', '/auth/login', { username, password }, 400)
    await page.getByLabel('用户名', { exact: true }).fill(username)
    await page.getByLabel('密码', { exact: true }).fill(nextPassword)
    await page.getByRole('button', { name: '进入忆知', exact: true }).click()
    // ProtectedRoute remembers /profile; successful login returns to that page.
    await expect(page).toHaveURL(/\/profile$/)
    await expect(page.getByLabel('昵称', { exact: true })).toHaveValue('资料持久化验证')
    const profile = await request(page.request, 'get', '/profile')
    expect(profile).toMatchObject({ nickname: '资料持久化验证', email: `${username}@example.test`, role: 'user', hasAvatar: true, emailVerified: false })
    expect(await (await page.request.get('/api/v1/profile/avatar')).body()).toEqual(avatar)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('profile-saved.png'), fullPage: true })
    await testInfo.attach('profile-verification.json', { body: JSON.stringify({ avatar_bytes_preserved: true,
      profile_survives_reload_and_password_change: true, all_old_sessions_revoked: true, old_password_rejected: true,
      new_password_browser_login: true }), contentType: 'application/json' })
  } finally {
    if (account) {
      // Cleanup can also recover after failure between changing the password and logging in.
      if ((await page.request.get('/api/v1/profile')).status() !== 200) {
        const changed = await page.request.post('/api/v1/auth/login', { data: { username, password: nextPassword } })
        if (changed.status() !== 200) await request(page.request, 'post', '/auth/login', { username, password })
      }
      await request(page.request, 'delete', '/profile/account')
    }
    await previousSession?.dispose()
  }
})
