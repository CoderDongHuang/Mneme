import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent、MySQL 和管理员配置')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('整站恢复真实权限和执行器状态，隔离归档校验与锁定迟到响应', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  const gateway = container('java-gateway'), mysql = container('mysql')
  for (const id of [gateway, mysql]) expect(id).toMatch(/^[a-f0-9]+$/)
  const env = JSON.parse(execFileSync('docker', ['inspect', '--format', '{{json .Config.Env}}', gateway], { encoding: 'utf8' }))
  const adminToken = env.find(value => value.startsWith('ADMIN_API_TOKEN='))?.slice('ADMIN_API_TOKEN='.length)
  expect(Boolean(adminToken && adminToken.length >= 32)).toBe(true)
  const setting = name => env.find(value => value.startsWith(`${name}=`))?.slice(name.length + 1) || ''
  const workerConfigured = Boolean(setting('RECOVERY_WORKER_URL').trim() && setting('RECOVERY_WORKER_TOKEN').length >= 32)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', ''), username = `sitestate_${suffix.slice(0, 12)}`
  let account
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const site = () => page.getByRole('region', { name: '整站备份与恢复', exact: true })
  const unlock = async value => {
    await page.getByLabel('管理员凭证', { exact: true }).fill(value)
    await page.getByRole('button', { name: '验证权限', exact: true }).click()
  }
  const lock = () => page.getByRole('button', { name: '锁定', exact: true }).click()
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await site().scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  let destructiveRequests = 0, previewRequests = 0
  // Jobs and drill dispatch must never reach the actual recovery executor.
  // Only explicitly installed browser preview fixtures may answer a POST.
  await page.route('**/api/v1/admin/recovery**', route => {
    if (route.request().method() !== 'GET') { destructiveRequests++; return route.abort() }
    return route.continue()
  })
  try {
    account = await api('post', '/auth/register', { username, password: `SiteRecovery!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    const denied = await page.request.get('/api/v1/admin/recovery/site', { headers: { 'X-Admin-Token': adminToken } })
    expect(denied.status()).toBe(403)
    expect(sql(`UPDATE user SET role='admin' WHERE id=${account.userId} AND username='${username}' AND status='active'; SELECT role FROM user WHERE id=${account.userId}`)).toBe('admin')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/recovery')
    await page.getByRole('button', { name: '管理员整站灾备', exact: true }).click()
    await unlock('invalid-credential-'.padEnd(32, 'x'))
    await expect(site().getByText('整站任务加载失败：管理员凭证无效', { exact: true })).toBeVisible()
    await expect(site().getByText('暂无整站操作记录。', { exact: true })).toHaveCount(0)
    await lock()
    const actual = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/admin/recovery/site')
    await unlock(adminToken)
    const response = await actual, result = await response.json()
    if (response.ok()) {
      expect(workerConfigured).toBe(true)
      expect(result.code).toBe(200)
      expect(Array.isArray(result.data.jobs) && Array.isArray(result.data.archives)).toBe(true)
      await expect(site()).toHaveAttribute('aria-busy', 'false')
      await expect(site().getByRole('alert')).toHaveCount(0)
    } else {
      expect(response.status()).toBe(400)
      expect(result.code).toBe(400)
      if (workerConfigured) {
        expect([
          '宿主机恢复执行器不可用或校验超时，请检查服务后刷新任务历史，避免重复提交。',
          '整站恢复请求被拒绝，请检查归档、确认语句与摘要，或等待现有任务完成。',
        ]).toContain(result.message)
      } else {
        expect(result.message).toBe('整站恢复执行器未配置。请在 Docker 宿主机启动 scripts/recovery_worker.py 并设置恢复服务地址与凭证。')
      }
      await expect(site().getByText(`整站任务加载失败：${result.message}`, { exact: true })).toBeVisible()
      await expect(site().getByText('暂无整站操作记录。', { exact: true })).toHaveCount(0)
    }
    await shot('site-real-authorization.png')
    await lock()
    const archives = [{ name: 'site-a.tar.gz', bytes: 1024 }, { name: 'site-b.tar.gz', bytes: 2048 }]
    const jobs = [{ id: 'site-fixture-1', action: 'backup', status: 'interrupted', created_at: '2026-11-02T00:00:00Z', message: 'Executor interrupted; inspect report.' }]
    const payload = value => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: value }) })
    let mode = 'failure', releaseHistory, historyReads = 0
    await page.route('**/api/v1/admin/recovery/site', async route => {
      if (route.request().method() !== 'GET') { destructiveRequests++; return route.abort() }
      historyReads++
      if (mode === 'failure') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取暂不可用' }) })
      if (mode === 'pending') await new Promise(resolve => { releaseHistory = resolve })
      return route.fulfill(payload(mode === 'empty' ? { jobs: [], archives: [] } : { jobs, archives })).catch(() => {})
    })
    await unlock(adminToken)
    await expect(site().getByText('整站任务加载失败：读取暂不可用', { exact: true })).toBeVisible()
    await expect(site().getByText('暂无整站操作记录。', { exact: true })).toHaveCount(0)
    mode = 'success'
    await site().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(site().getByText('已中断', { exact: true })).toBeVisible()
    mode = 'failure'
    await site().getByRole('button', { name: '刷新任务状态', exact: true }).click()
    await expect(site().getByText('已有整站数据可能不是最新状态，操作已暂停。', { exact: true })).toBeVisible()
    await expect(site().getByLabel('选择整站归档', { exact: true })).toBeDisabled()
    await expect(site().getByRole('button', { name: '创建整站备份', exact: true })).toBeDisabled()
    await shot('site-stale-history.png')
    mode = 'success'
    await site().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(site().getByLabel('选择整站归档', { exact: true })).toBeEnabled()
    let releasePreview
    await page.route('**/api/v1/admin/recovery/site/preview', async route => {
      expect(route.request().method()).toBe('POST'); previewRequests++
      const archive = route.request().postDataJSON().archive
      if (archive === 'site-a.tar.gz') await new Promise(resolve => { releasePreview = resolve })
      return route.fulfill(payload({ name: archive, verified: true, compatible: true, sha256: 'a'.repeat(64), security: { encrypted: true, signed: true }, metadata: { application_schema_max: 30 }, overwrites: ['MySQL', 'Redis'] })).catch(() => {})
    })
    await site().getByLabel('选择整站归档', { exact: true }).selectOption('site-a.tar.gz')
    await site().getByRole('button', { name: '验证完整性与兼容性', exact: true }).click()
    await expect(site().getByText('正在校验所选归档', { exact: true })).toBeVisible()
    await expect.poll(() => typeof releasePreview).toBe('function')
    await site().getByLabel('选择整站归档', { exact: true }).selectOption('site-b.tar.gz')
    await site().getByRole('button', { name: '验证完整性与兼容性', exact: true }).click()
    await expect(site().getByText('清单、文件与数据库版本校验通过', { exact: true })).toBeVisible()
    releasePreview()
    await shot('site-verified-preview.png')
    await expect(site().getByLabel('选择整站归档', { exact: true })).toHaveValue('site-b.tar.gz')
    mode = 'pending'
    const before = historyReads
    await site().getByRole('button', { name: '刷新任务状态', exact: true }).click()
    await expect.poll(() => historyReads).toBe(before + 1)
    await expect(site().getByText('正在读取整站任务', { exact: true })).toBeVisible()
    await lock(); releaseHistory()
    mode = 'empty'
    await unlock(adminToken)
    await expect(site().getByText('暂无整站操作记录。', { exact: true })).toBeVisible()
    await expect(site().getByLabel('选择整站归档', { exact: true })).toHaveValue('')
    await expect(site().getByText('整站恢复预览', { exact: true })).toHaveCount(0)
    await expect(site().getByText('已中断', { exact: true })).toHaveCount(0)
    await shot('site-clean-scope.png')
    await lock()
    expect(await page.evaluate(secret => ![...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(secret)), adminToken)).toBe(true)
    expect(destructiveRequests).toBe(0)
    expect(previewRequests).toBe(2)
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
  }
})

