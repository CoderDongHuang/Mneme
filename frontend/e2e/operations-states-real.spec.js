import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent、MySQL 和管理员配置')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实管理员权限与运维、审计独立失败恢复，锁定不保留凭证或旧数据', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  const gateway = container('java-gateway'), mysql = container('mysql')
  for (const id of [gateway, mysql]) expect(id).toMatch(/^[a-f0-9]+$/)
  // Keep the deployed credential in memory only, never in test output/artifacts.
  const env = JSON.parse(execFileSync('docker', ['inspect', '--format', '{{json .Config.Env}}', gateway], { encoding: 'utf8' }))
  const adminToken = env.find(value => value.startsWith('ADMIN_API_TOKEN='))?.slice('ADMIN_API_TOKEN='.length)
  expect(Boolean(adminToken && adminToken.length >= 32)).toBe(true)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  let account, failSnapshot = false, failAudit = false, snapshotReads = 0
  const suffix = randomUUID().replaceAll('-', '')
  const username = `opsstate_${suffix.slice(0, 12)}`
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
  const audit = () => page.getByRole('region', { name: '操作审计', exact: true })
  const unlock = async value => {
    await page.getByLabel('管理员凭证', { exact: true }).fill(value)
    await page.getByRole('button', { name: '验证权限', exact: true }).click()
  }
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    account = await api('post', '/auth/register', { username, password: `Operations!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    const denied = await page.request.get('/api/v1/admin/operations', { headers: { 'X-Admin-Token': adminToken } })
    expect(denied.status()).toBe(403)
    expect(sql(`UPDATE user SET role='admin' WHERE id=${account.userId} AND username='${username}' AND status='active'; SELECT role FROM user WHERE id=${account.userId}`)).toBe('admin')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/operations')
    await unlock('invalid-credential-'.padEnd(32, 'x'))
    await expect(page.getByText('运维状态加载失败：管理员凭证无效', { exact: true })).toBeVisible()
    await expect(audit().getByText('审计记录加载失败：管理员凭证无效', { exact: true })).toBeVisible()
    await expect(page.getByText('暂无记录', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '锁定', exact: true }).click()
    failSnapshot = true; failAudit = true
    await page.route('**/api/v1/admin/operations', route => {
      snapshotReads++
      return failSnapshot ? failure(route) : route.continue()
    })
    await page.route('**/api/v1/admin/audit', route => failAudit ? failure(route) : route.continue())
    await unlock(adminToken)
    await expect(page.getByText('运维状态加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(audit().getByText('审计记录加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText('暂无记录', { exact: true })).toHaveCount(0)
    await shot('operations-unavailable.png')
    failAudit = false
    const readsBefore = snapshotReads
    const auditResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/admin/audit' && response.ok())
    await audit().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    const logs = (await (await auditResponse).json()).data
    expect(Array.isArray(logs)).toBe(true)
    await expect(audit().getByRole('alert')).toHaveCount(0)
    expect(snapshotReads).toBe(readsBefore)
    await expect(page.getByText('运维状态加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    failSnapshot = false
    await page.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(page.getByRole('heading', { name: '依赖健康', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '刷新运维状态', exact: true })).toBeEnabled()
    await shot('operations-recovered.png')
    failSnapshot = true; failAudit = true
    await page.getByRole('button', { name: '刷新运维状态', exact: true }).click()
    await expect(page.getByText('已有运维数据可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(audit().getByText('已有审计记录可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '依赖健康', exact: true })).toBeVisible()
    await shot('operations-stale.png')
    await page.getByRole('button', { name: '锁定', exact: true }).click()
    await expect(page.getByRole('heading', { name: '依赖健康', exact: true })).toHaveCount(0)
    await expect(audit()).toHaveCount(0)
    expect(await page.evaluate(secret => ![...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(secret)), adminToken)).toBe(true)
    await expect(page.getByLabel('管理员凭证', { exact: true })).toHaveValue('')
    await page.reload()
    await expect(page.getByLabel('管理员凭证', { exact: true })).toHaveValue('')
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
  }
})
