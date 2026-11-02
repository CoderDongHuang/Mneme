import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent、MySQL 和管理员配置')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('恢复演练真实权限与未配置状态，隔离读取故障和锁定迟到响应', async ({ page }, testInfo) => {
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
  let account
  const suffix = randomUUID().replaceAll('-', '')
  const username = `drillstate_${suffix.slice(0, 12)}`
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
  const history = () => page.getByRole('region', { name: '演练历史', exact: true })
  const report = () => page.getByRole('region', { name: '演练报告', exact: true })
  const unlock = async value => {
    await page.getByLabel('管理员凭证', { exact: true }).fill(value)
    await page.getByRole('button', { name: '验证权限', exact: true }).click()
  }
  const lock = () => page.getByRole('button', { name: '锁定', exact: true }).click()
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await history().scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  // No restore/backup/dispatch POST is permitted by this read-state regression.
  let destructiveRequests = 0
  await page.route('**/api/v1/admin/recovery**', route => {
    if (route.request().method() !== 'GET') { destructiveRequests++; return route.abort() }
    return route.continue()
  })
  try {
    account = await api('post', '/auth/register', { username, password: `Recovery!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    const denied = await page.request.get('/api/v1/admin/recovery', { headers: { 'X-Admin-Token': adminToken } })
    expect(denied.status()).toBe(403)
    expect(sql(`UPDATE user SET role='admin' WHERE id=${account.userId} AND username='${username}' AND status='active'; SELECT role FROM user WHERE id=${account.userId}`)).toBe('admin')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/recovery')
    await page.getByRole('button', { name: '管理员整站灾备', exact: true }).click()
    await unlock('invalid-credential-'.padEnd(32, 'x'))
    await expect(history().getByText('演练历史加载失败：管理员凭证无效', { exact: true })).toBeVisible()
    await expect(history().getByText('暂无演练历史', { exact: true })).toHaveCount(0)
    await lock()
    const actual = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/admin/recovery')
    await unlock(adminToken)
    const response = await actual
    const result = await response.json()
    if (response.ok()) {
      expect(Array.isArray(result.data.runs)).toBe(true)
      await expect(history()).toHaveAttribute('aria-busy', 'false')
      await expect(history().getByRole('alert')).toHaveCount(0)
    } else {
      // Local/CI omit GitHub workflow credentials. Show the actual failure,
      // never fabricate successful workflow history or dispatch a real run.
      expect(response.status()).toBe(400)
      expect(result.message).toBe('恢复工作流未配置')
      await expect(history().getByText('演练历史加载失败：恢复工作流未配置', { exact: true })).toBeVisible()
      await expect(history().getByText('暂无演练历史', { exact: true })).toHaveCount(0)
    }
    await shot('recovery-real-authorization.png')
    await lock()
    // Scoped browser GET fixtures exercise cached/late responses unavailable
    // from an unconfigured workflow. Authorization above is always real.
    let mode = 'failure', release, fixtureReads = 0
    const runs = [{ id: 901, run_number: 901, status: 'queued', created_at: '2026-11-02T00:00:00Z' }]
    const payload = value => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: value }) })
    await page.route('**/api/v1/admin/recovery', async route => {
      if (route.request().method() !== 'GET') { destructiveRequests++; return route.abort() }
      fixtureReads++
      if (mode === 'failure') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取暂不可用' }) })
      if (mode === 'pending') {
        await new Promise(resolve => { release = resolve })
        return route.fulfill(payload({ runs })).catch(() => {})
      }
      return route.fulfill(payload({ runs: mode === 'empty' ? [] : runs }))
    })
    await unlock(adminToken)
    await expect(history().getByText('演练历史加载失败：读取暂不可用', { exact: true })).toBeVisible()
    await expect(history().getByText('暂无演练历史', { exact: true })).toHaveCount(0)
    mode = 'success'
    await history().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(history().getByText(/#901/)).toBeVisible()
    await expect(history().getByText('等待领取', { exact: true })).toBeVisible()
    mode = 'failure'
    await page.getByRole('button', { name: '刷新历史', exact: true }).click()
    await expect(history().getByText('已有演练历史可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(history().getByText(/#901/)).toBeVisible()
    await shot('recovery-stale-history.png')
    let releaseReport
    await page.route('**/api/v1/admin/recovery/901', async route => {
      await new Promise(resolve => { releaseReport = resolve })
      return route.fulfill(payload({ run: { id: 901, run_number: 901 }, jobs: [], artifacts: [] })).catch(() => {})
    })
    await history().getByRole('button', { name: '校验与报告', exact: true }).click()
    await expect(report().getByText('正在读取演练报告', { exact: true })).toBeVisible()
    mode = 'pending'
    const before = fixtureReads
    await page.getByRole('button', { name: '刷新历史', exact: true }).click()
    await expect.poll(() => fixtureReads).toBe(before + 1)
    await expect(history().getByText('正在读取演练历史', { exact: true })).toBeVisible()
    await page.getByLabel('确认语句', { exact: true }).fill('ISOLATED DRILL')
    await lock()
    release(); releaseReport()
    mode = 'empty'
    await unlock(adminToken)
    await expect(history().getByText('暂无演练历史', { exact: true })).toBeVisible()
    await expect(history().getByText(/#901/)).toHaveCount(0)
    await expect(report()).toHaveCount(0)
    await expect(page.getByLabel('确认语句', { exact: true })).toHaveValue('')
    await shot('recovery-clean-scope.png')
    await lock()
    expect(await page.evaluate(secret => ![...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(secret)), adminToken)).toBe(true)
    await expect(page.getByLabel('管理员凭证', { exact: true })).toHaveValue('')
    expect(destructiveRequests).toBe(0)
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
  }
})
