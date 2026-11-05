import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

for (const receipt of ['invalid', 'lost']) test(`真实资料业务校验及 ${receipt} 保存、头像回执只读核对`, async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(20000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B mneme'], { input: 'SET NAMES utf8mb4;\n' + query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', ''), username = `profileread_${suffix.slice(0, 10)}`, password = `Profile!${suffix}`
  let account, cleanup, badRead = true, failCheck = false, writes = 0, uploads = 0, avatarPath
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  async function api(context, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await context[method]('/api/v1' + path, { data, timeout: 45000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after']); expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: true, animations: 'disabled' })
  }
  try {
    account = await api(page.request, 'post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await page.addInitScript(value => {
      if (!sessionStorage.getItem('profile-read-initialized')) {
        localStorage.setItem('mneme_auth', JSON.stringify(value))
        sessionStorage.setItem('profile-read-initialized', 'true')
      }
    }, account)
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/profile', async route => {
      if (route.request().method() === 'GET') {
        if (failCheck) return route.fulfill({ status: 503, json: { code: 503, message: '核对读取暂不可用' } })
        const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
        return route.fulfill(badRead ? { response, json: { ...body, data: { ...body.data, nickname: {} } } } : { response })
      }
      if (route.request().method() !== 'PATCH') return route.continue()
      writes++
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200); expect(body.code).toBe(200)
      return route.fulfill(receipt === 'invalid' ? { response, json: { ...body, data: { ...body.data, nickname: {} } } } : { status: 503, json: { code: 503, message: '保存回执丢失' } })
    })
    await page.route('**/api/v1/profile/avatar', async route => {
      if (route.request().method() !== 'POST') return route.continue()
      uploads++
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200); expect(body.code).toBe(200)
      return route.fulfill(receipt === 'invalid' ? { response, json: { ...body, data: { ...body.data, hasAvatar: false } } } : { status: 503, json: { code: 503, message: '头像回执丢失' } })
    })
    await page.goto('/profile')
    await expect(page.getByText('个人资料响应格式不正确', { exact: true })).toBeVisible()
    await expect(page.getByLabel('昵称', { exact: true })).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('mneme_auth')).username)).toBe(username)
    await shot('profile-invalid-read.png')
    badRead = false
    await page.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    const nickname = page.getByLabel('昵称', { exact: true }), draft = `资料核对-${suffix.slice(0, 6)}`
    await nickname.fill(draft)
    await page.getByRole('button', { name: '保存资料', exact: true }).click()
    await expect(page.getByText('资料操作结果尚未确认，请先核对服务端资料。', { exact: true })).toBeVisible()
    await expect(nickname).toHaveValue(draft); await expect(nickname).toBeDisabled()
    await expect(page.getByText('个人资料已保存', { exact: true })).toHaveCount(0)
    failCheck = true
    await page.getByRole('button', { name: '核对已保存资料', exact: true }).click()
    await expect(page.getByText('核对读取暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '保存资料', exact: true })).toBeDisabled()
    await shot('profile-save-unconfirmed.png')
    failCheck = false
    await page.getByRole('button', { name: '核对已保存资料', exact: true }).click()
    const check = page.getByRole('region', { name: '核对个人资料', exact: true })
    await expect(check.locator('dd').filter({ hasText: draft })).toBeVisible()
    await shot('profile-server-snapshot.png')
    await check.getByRole('button', { name: receipt === 'invalid' ? '保留草稿，继续编辑' : '采用服务端资料', exact: true }).click()
    await expect(nickname).toBeEnabled(); await expect(nickname).toHaveValue(draft)
    expect(writes).toBe(1)
    expect(await api(cleanup, 'get', '/profile')).toMatchObject({ nickname: draft, username })
    const avatar = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=', 'base64')
    await page.locator('input[type=file]').setInputFiles({ name: 'profile-avatar.png', mimeType: 'image/png', buffer: avatar })
    await expect(page.getByText('资料操作结果尚未确认，请先核对服务端资料。', { exact: true })).toBeVisible()
    await expect(page.getByText('头像已更新', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '核对已保存资料', exact: true }).click()
    await expect(check.getByText('已设置', { exact: true })).toBeVisible()
    await check.getByRole('button', { name: '采用服务端资料', exact: true }).click()
    await expect(page.getByAltText('当前头像')).toBeVisible()
    expect(uploads).toBe(1)
    expect(await (await cleanup.get('/api/v1/profile/avatar')).body()).toEqual(avatar)
    expect(sql(`SELECT nickname FROM user WHERE id=${account.userId}`)).toBe(draft)
    avatarPath = sql(`SELECT avatar_path FROM user WHERE id=${account.userId}`)
    expect(avatarPath).toMatch(/avatars\//)
    await page.reload()
    await expect(nickname).toHaveValue(draft)
    await expect(page.getByAltText('当前头像')).toBeVisible()
    await shot('profile-verified.png')
    expect(writes).toBe(1); expect(uploads).toBe(1); expect(pageErrors).toEqual([])
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api(page.request, 'post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api(cleanup, 'delete', '/profile/account')
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
        expect(sql(`SELECT COUNT(*) FROM auth_session WHERE user_id=${account.userId}`)).toBe('0')
        if (avatarPath) {
          const gateway = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=java-gateway', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
          expect(gateway).toMatch(/^[a-f0-9]+$/)
          execFileSync('docker', ['exec', gateway, 'test', '!', '-e', avatarPath])
        }
      } finally { await cleanup.dispose() }
    }
  }
})
