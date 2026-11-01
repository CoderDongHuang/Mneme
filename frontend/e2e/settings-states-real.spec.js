import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实模型配置独立读取、后端拒绝无密钥启用、保存锁定及刷新读回', async ({ page }, testInfo) => {
  test.setTimeout(150000)
  page.setDefaultTimeout(15000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  let account, failModel = true, failHealth = true, modelReads = 0, saveCount = 0, releaseSave
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const failure = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取服务暂不可用' }) })
  const shot = async name => {
    await page.getByRole('heading', { name: '个人模型服务', exact: true }).scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    account = await api('post', '/auth/register', { username: `settingsstate_${suffix.slice(0, 12)}`, password: `Settings!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/settings/models', route => {
      if (route.request().method() !== 'GET') return route.continue()
      modelReads++
      return failModel ? failure(route) : route.continue()
    })
    await page.route('**/api/v1/health/config', route => failHealth ? failure(route) : route.continue())
    await page.goto('/settings')
    await expect(page.getByText('模型配置加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText('服务状态加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByLabel('模型名称', { exact: true })).toHaveCount(0)
    await shot('settings-unavailable.png')
    failModel = false
    await page.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    const name = page.getByLabel('模型名称', { exact: true })
    await expect(name).toBeVisible()
    const draft = `settings-state-${suffix.slice(0, 8)}`
    await name.fill(draft)
    const before = modelReads
    failHealth = false
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await expect(page.getByText('服务状态加载失败：读取服务暂不可用', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '刷新状态', exact: true })).toBeEnabled()
    expect(modelReads).toBe(before)
    await expect(name).toHaveValue(draft)
    const enabled = page.getByLabel('为我的请求启用个人模型', { exact: true })
    await enabled.check()
    const rejected = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/settings/models' && response.request().method() === 'PUT')
    await page.getByRole('button', { name: '保存配置', exact: true }).click()
    expect((await rejected).status()).toBe(400)
    await expect(page.getByRole('form', { name: '个人模型服务' })).toHaveAttribute('aria-busy', 'false')
    await expect(page.getByRole('alert')).toHaveCount(1)
    await expect(name).toHaveValue(draft)
    await expect(enabled).toBeChecked()
    await shot('settings-draft-retained.png')
    await enabled.uncheck()
    const gate = new Promise(resolve => { releaseSave = resolve })
    await page.route('**/api/v1/settings/models', async route => {
      if (route.request().method() !== 'PUT') return route.fallback()
      saveCount++
      await gate
      return route.continue()
    })
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/settings/models' && response.request().method() === 'PUT' && response.ok())
    await page.getByRole('button', { name: '保存配置', exact: true }).click()
    await expect(name).toBeDisabled()
    await expect(page.getByLabel('服务商', { exact: true })).toBeDisabled()
    await expect(page.getByLabel('API 密钥', { exact: true })).toBeDisabled()
    await expect(enabled).toBeDisabled()
    await expect(page.getByLabel('保存时清除已存密钥（请先关闭个人模型）', { exact: true })).toBeDisabled()
    failHealth = true
    await page.getByRole('button', { name: '刷新状态', exact: true }).click()
    await expect(page.getByText('服务状态加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    releaseSave()
    expect((await saved).status()).toBe(200)
    await expect(page.getByText('模型配置已保存', { exact: true })).toBeVisible()
    await expect(page.getByText('服务状态加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    expect(saveCount).toBe(1)
    const readback = await api('get', '/settings/models')
    expect(readback).toMatchObject({ model: draft, enabled: false, hasKey: false })
    expect(readback.apiKey).toBeUndefined()
    await shot('settings-saved.png')
    await page.reload()
    await expect(page.getByLabel('模型名称', { exact: true })).toHaveValue(draft)
    await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
    await expect(page.getByLabel('为我的请求启用个人模型', { exact: true })).not.toBeChecked()
  } finally {
    releaseSave?.()
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
  }
})
