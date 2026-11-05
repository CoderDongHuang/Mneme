import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

for (const receipt of ['invalid', 'lost']) test(`真实设置业务数据校验及 ${receipt} 保存回执只读核对`, async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(20000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', ''), username = `settingsread_${suffix.slice(0, 10)}`, password = `Settings!${suffix}`
  let account, cleanup, badModel = true, badHealth = true, writes = 0, modelReads = 0, reconciliationFails = false
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
    await page.getByRole('heading', { name: '个人模型服务', exact: true }).scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: true, animations: 'disabled' })
  }
  try {
    account = await api(page.request, 'post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/health/config', async route => {
      const response = await route.fetch(); expect(response.status()).toBe(200)
      return route.fulfill(badHealth ? { response, json: {} } : { response })
    })
    await page.route('**/api/v1/settings/models', async route => {
      if (route.request().method() === 'GET') {
        modelReads++
        if (reconciliationFails) return route.fulfill({ status: 503, json: { code: 503, message: '核对读取暂不可用' } })
        const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
        return route.fulfill(badModel ? { response, json: { ...body, data: { ...body.data, hasKey: {} } } } : { response })
      }
      if (route.request().method() !== 'PUT') return route.continue()
      writes++
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200); expect(body.code).toBe(200)
      return route.fulfill(receipt === 'invalid' ? { response, json: { ...body, data: { ...body.data, model: {} } } } : { status: 503, json: { code: 503, message: '保存回执丢失' } })
    })
    await page.goto('/settings')
    await expect(page.getByText('模型配置加载失败：模型配置响应格式不正确', { exact: true })).toBeVisible()
    await expect(page.getByText('服务状态加载失败，请重试。', { exact: true })).toBeVisible()
    await expect(page.getByText('服务已连接', { exact: true })).toHaveCount(0)
    await expect(page.getByLabel('模型名称', { exact: true })).toHaveCount(0)
    await shot('settings-invalid-reads.png')
    badModel = false
    await page.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    const model = page.getByLabel('模型名称', { exact: true }), key = page.getByLabel('API 密钥', { exact: true })
    const draft = `settings-read-${suffix.slice(0, 8)}`, fakeKey = 'e2e-placeholder-not-a-real-key'
    await model.fill(draft); await key.fill(fakeKey)
    const before = modelReads
    badHealth = false
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await expect(page.getByText('服务状态加载失败，请重试。', { exact: true })).toHaveCount(0)
    expect(modelReads).toBe(before)
    await expect(model).toHaveValue(draft); await expect(key).toHaveValue(fakeKey)
    await page.getByRole('button', { name: '保存配置', exact: true }).click()
    await expect(page.getByText('模型保存结果尚未确认，请先核对服务端配置。', { exact: true })).toBeVisible()
    await expect(model).toBeDisabled(); await expect(key).toHaveValue(fakeKey)
    await expect(page.getByRole('button', { name: '保存配置', exact: true })).toBeDisabled()
    await expect(page.getByText('模型配置已保存', { exact: true })).toHaveCount(0)
    reconciliationFails = true
    await page.getByRole('button', { name: '核对已保存模型配置', exact: true }).click()
    await expect(page.getByText('模型配置加载失败：核对读取暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '采用服务端配置', exact: true })).toHaveCount(0)
    await shot('settings-unconfirmed-save.png')
    reconciliationFails = false
    await page.getByRole('button', { name: '核对已保存模型配置', exact: true }).click()
    const check = page.getByRole('region', { name: '核对模型配置', exact: true })
    await expect(check.getByText(draft, { exact: true })).toBeVisible()
    await shot('settings-server-snapshot.png')
    await check.getByRole('button', { name: receipt === 'invalid' ? '保留草稿，继续编辑' : '采用服务端配置', exact: true }).click()
    await expect(model).toBeEnabled(); await expect(model).toHaveValue(draft)
    await expect(key).toHaveValue(receipt === 'invalid' ? fakeKey : '')
    expect(writes).toBe(1)
    const saved = await api(cleanup, 'get', '/settings/models')
    expect(saved).toMatchObject({ model: draft, enabled: false, hasKey: true }); expect(saved.apiKey).toBeUndefined()
    expect(sql(`SELECT COUNT(*) FROM user_model_config WHERE user_id=${account.userId}`)).toBe('1')
    await page.reload()
    await expect(page.getByLabel('模型名称', { exact: true })).toHaveValue(draft)
    await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
    await shot('settings-verified-configuration.png')
    expect(writes).toBe(1); expect(pageErrors).toEqual([])
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api(page.request, 'post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api(cleanup, 'delete', '/profile/account')
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
        expect(sql(`SELECT COUNT(*) FROM user_model_config WHERE user_id=${account.userId}`)).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
