import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、MySQL 和 Mailpit')
// Codes and passwords must not be captured in traces, video or failure screenshots.
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实邮箱所有权、重置密码和换绑失效在桌面与移动端成立', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000)
  const suffix = randomUUID().replaceAll('-', '')
  const username = `emailqa_${suffix.slice(0, 12)}`
  const email = `${username}@example.test`, nextEmail = `${username}-new@example.test`
  const password = `EmailQA!${suffix}`, nextPassword = `Changed!${suffix}`
  const inbox = await playwright.request.newContext({ baseURL: process.env.MNEME_MAILPIT_URL || 'http://127.0.0.1:8025' })
  let account
  const ownMailIds = new Set()
  async function api(method, path, data, expected = 200) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && expected !== 429) {
        await page.waitForTimeout(Math.min(60000, Math.max(1000, Number(response.headers()['retry-after'] || 5) * 1000)))
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(expected)
      const body = await response.json()
      expect(body.code).toBe(expected)
      return body.data
    }
    throw new Error('Authentication rate limit did not recover')
  }
  async function messages(address, subject) {
    const response = await inbox.get('/api/v1/search', { params: { query: `to:${address}`, limit: 100 } })
    expect(response.ok(), 'Mailpit search').toBe(true)
    const list = (await response.json()).messages || []
    for (const item of list) ownMailIds.add(item.ID)
    return list.filter(item => item.To?.some(recipient => recipient.Address === address) && item.Subject.includes(subject))
  }
  async function mailCode(address, subject) {
    let list
    await expect.poll(async () => { list = await messages(address, subject); return list.length }, { timeout: 15000 }).toBeGreaterThan(0)
    const response = await inbox.get(`/api/v1/message/${list[0].ID}`)
    expect(response.ok()).toBe(true)
    const value = (await response.json()).Text?.match(/\b[0-9a-f]{64}\b/)?.[0]
    expect(Boolean(value), 'Mail contains a valid code').toBe(true)
    return value
  }
  async function saveEmail(value) {
    await page.getByLabel('绑定邮箱').fill(value)
    await page.getByRole('button', { name: '保存资料', exact: true }).click()
    await expect(page.getByText('个人资料已保存', { exact: true })).toBeVisible()
  }
  try {
    account = await api('post', '/auth/register', { username, password })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/profile')
    await saveEmail(email)
    await expect(page.getByText('当前邮箱尚未验证，不能用于找回密码。')).toBeVisible()
    await api('post', '/auth/password-reset/request', { username, email })
    expect((await messages(email, '密码重置')).length).toBe(0)
    await page.getByRole('button', { name: '发送邮箱验证码', exact: true }).click()
    await expect(page.getByText('验证邮件已提交至邮件服务器，请检查收件箱。验证码 15 分钟内有效。')).toBeVisible()
    const code = await mailCode(email, '邮箱验证')
    await api('post', '/profile/email-verification/request', { email }, 429)
    await page.getByLabel('邮箱验证码').fill('0'.repeat(64))
    await page.getByRole('button', { name: '验证邮箱', exact: true }).click()
    await expect(page.getByText('邮箱验证码无效或已过期', { exact: true })).toBeVisible()
    await page.getByLabel('邮箱验证码').fill(code)
    await page.getByRole('button', { name: '验证邮箱', exact: true }).click()
    await expect(page.getByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
    await page.reload()
    await expect(page.getByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
    expect((await api('get', '/profile')).emailVerified).toBe(true)
    await api('post', '/profile/email-verification/confirm', { token: code }, 400)
    await api('post', '/auth/password-reset/request', { username, email })
    const reset = await mailCode(email, '密码重置')
    await api('post', '/auth/password-reset/confirm', { token: reset, newPassword: nextPassword })
    await api('post', '/auth/password-reset/confirm', { token: reset, newPassword: password }, 400)
    await api('post', '/auth/login', { username, password }, 400)
    await api('post', '/auth/login', { username, password: nextPassword })
    await api('post', '/auth/password-reset/request', { username, email })
    await expect.poll(async () => (await messages(email, '密码重置')).length).toBe(2)
    const beforeChange = await mailCode(email, '密码重置')
    await page.reload()
    await saveEmail(nextEmail)
    await expect(page.getByText('当前邮箱尚未验证，不能用于找回密码。')).toBeVisible()
    await api('post', '/auth/password-reset/confirm', { token: beforeChange, newPassword: password }, 400)
    await api('post', '/auth/password-reset/request', { username, email: nextEmail })
    expect((await messages(nextEmail, '密码重置')).length).toBe(0)
    expect((await api('get', '/profile')).emailVerified).toBe(false)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('email-unverified.png'), fullPage: true })
    await page.getByRole('button', { name: '发送邮箱验证码', exact: true }).click()
    const nextCode = await mailCode(nextEmail, '邮箱验证')
    await page.getByLabel('邮箱验证码').fill(nextCode)
    await page.getByRole('button', { name: '验证邮箱', exact: true }).click()
    await expect(page.getByText('当前邮箱已验证，可用于找回密码。')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('email-verified.png'), fullPage: true })
    await testInfo.attach('email-verification.json', { body: JSON.stringify({ viewport: testInfo.project.use.viewport,
      unverified_reset_blocked: true, verified_reset_completed: true, old_password_rejected: true,
      one_time_codes: true, email_change_invalidates_reset: true, reverified: true }), contentType: 'application/json' })
  } finally {
    if (account) await api('delete', '/profile/account')
    // Only delete this test's messages; never empty the shared mailbox.
    if (ownMailIds.size) {
      const cleanup = await inbox.delete('/api/v1/messages', { data: { IDs: [...ownMailIds] } })
      expect(cleanup.ok(), 'Remove only this test account’s messages').toBe(true)
    }
    await inbox.dispose()
  }
})
