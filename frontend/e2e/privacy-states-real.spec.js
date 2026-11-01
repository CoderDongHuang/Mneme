import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('隐私读取独立恢复，真实保存和 Trace 删除不被审计读取失败抹去', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  let account, otherAccount, other, failPolicy = true, failLogs = true, writes = 0
  async function api(client, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await client[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  async function clickRequest(button, method, path) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1' + path && response.request().method() === method)
      await button.click()
      const response = await pending
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      return
    }
  }
  const fail = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取服务暂不可用' }) })
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false })
  }
  const containers = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
  expect(containers).toHaveLength(1)
  const traceFixture = (mode, userId) => {
    expect(String(userId)).toMatch(/^\d+$/)
    const script = `import sys
from app.agents.trace_store import agent_trace_store as store
from app.storage.mysql import connection as mysql_connection
mode, user_id = sys.argv[1:]
if mode == 'seed':
    store.record(user_id, 'privacy-qa', 'privacy-qa', 'completed')
else:
    if store.shared:
        with mysql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute('SELECT COUNT(*) FROM agent_trace WHERE user_id=%s', (user_id,))
            print(cursor.fetchone()[0])
            cursor.close()
    else:
        with store._connect() as connection:
            print(connection.execute('SELECT COUNT(*) FROM agent_trace WHERE user_id=?', (user_id,)).fetchone()[0])
`
    return execFileSync('docker', ['exec', containers[0], 'python', '-c', script, mode, String(userId)], { encoding: 'utf8', timeout: 15000 }).trim()
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api(page.request, 'post', '/auth/register', { username: `privacystate_${suffix.slice(0, 10)}`, password: `Privacy!${suffix}` })
    other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
    otherAccount = await api(other, 'post', '/auth/register', { username: `privacyother_${suffix.slice(0, 10)}`, password: `PrivacyOther!${suffix}` })
    for (const value of [account.userId, otherAccount.userId]) expect(String(value)).toMatch(/^\d+$/)
    // Seed only isolated QA traces, then verify physical deletion and tenant isolation.
    traceFixture('seed', account.userId); traceFixture('seed', otherAccount.userId)
    expect(traceFixture('count', account.userId)).toBe('1')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/privacy', route => route.request().method() === 'GET' && failPolicy ? fail(route) : route.continue())
    await page.route('**/api/v1/workspace/operations?*', route => failLogs ? fail(route) : route.continue())
    page.on('response', response => { if (new URL(response.url()).pathname === '/api/v1/privacy' && response.request().method() === 'PUT' && response.ok()) writes++ })
    await page.goto('/privacy')
    await expect(page.getByText('隐私策略加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    const history = page.getByRole('region', { name: '审计记录', exact: true })
    await expect(history.getByText('审计记录加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(history.getByText('暂无记录', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '导出数据', exact: true })).toBeEnabled()
    await shot('privacy-unavailable.png')
    failPolicy = false
    await clickRequest(page.getByRole('alert').filter({ hasText: '隐私策略加载失败：' }).getByRole('button'), 'GET', '/privacy')
    const saved = await api(page.request, 'get', '/privacy')
    const days = saved.trace_days === 1 ? Math.min(2, saved.trace_max_days) : 1
    await page.getByRole('spinbutton', { name: 'Trace 保留天数', exact: true }).fill(String(days))
    await page.getByRole('checkbox', { name: '允许外部模型处理', exact: true }).uncheck()
    await page.getByRole('textbox', { name: '删除确认', exact: true }).fill('未提交确认草稿')
    failLogs = false
    await clickRequest(history.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/operations')
    await expect(page.getByRole('spinbutton', { name: 'Trace 保留天数', exact: true })).toHaveValue(String(days))
    await expect(page.getByRole('textbox', { name: '删除确认', exact: true })).toHaveValue('未提交确认草稿')
    failLogs = true
    await clickRequest(page.getByRole('button', { name: '保存策略', exact: true }), 'PUT', '/privacy')
    await expect(page.getByText('策略保存完成', { exact: true })).toBeVisible()
    await expect(history.getByText('已有审计记录可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(history.getByText('暂无记录', { exact: true })).toHaveCount(0)
    const readback = await api(page.request, 'get', '/privacy')
    expect(readback.cloud_allowed).toBe(false)
    expect(readback.trace_days).toBe(days)
    expect((await api(page.request, 'get', '/workspace/operations?limit=200')).some(item => item.operation_type === 'privacy_policy' && item.status === 'completed')).toBe(true)
    await history.scrollIntoViewIfNeeded()
    await shot('privacy-saved-audit-unavailable.png')
    failLogs = false
    await clickRequest(history.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/operations')
    await expect(history.getByText('privacy_policy', { exact: true })).toBeVisible()
    failLogs = true
    await page.getByRole('textbox', { name: '删除确认', exact: true }).fill('DELETE TRACES')
    await clickRequest(page.getByRole('button', { name: '删除我的 Trace', exact: true }), 'DELETE', '/privacy/traces')
    await expect(page.getByText('Trace 删除完成', { exact: true })).toBeVisible()
    await expect(page.getByRole('textbox', { name: '删除确认', exact: true })).toHaveValue('')
    await expect(history.getByText('审计记录加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    expect(traceFixture('count', account.userId)).toBe('0')
    expect(traceFixture('count', otherAccount.userId)).toBe('1')
    failLogs = false
    await clickRequest(history.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/operations')
    await expect(history.getByText('privacy_trace_delete', { exact: true })).toBeVisible()
    await shot('privacy-recovered.png')
    expect(writes).toBe(1)
    await page.reload()
    await expect(page.getByRole('spinbutton', { name: 'Trace 保留天数', exact: true })).toHaveValue(String(days))
    await expect(page.getByRole('checkbox', { name: '允许外部模型处理', exact: true })).not.toBeChecked()
  } finally {
    if (account) await api(page.request, 'delete', '/profile/account')
    if (otherAccount) await api(other, 'delete', '/profile/account')
    await other?.dispose()
  }
})
