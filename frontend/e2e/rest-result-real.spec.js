import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、MySQL 和 Agent')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('普通 JSON 响应拒绝非法成功，真实资料写入与健康探针保持原契约', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const username = `restqa_${suffix.slice(0, 12)}`, password = `RestQA!${suffix}`
  let account, malformedRead = true, malformedWrite = true, writes = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, { data, timeout: 45000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      expect(body).toHaveProperty('data')
      return body.data
    }
  }
  const formatError = '服务返回的数据格式异常，请刷新核实后再操作'
  try {
    account = await api('post', '/auth/register', { username, password })
    expect(String(account.userId)).toMatch(/^\d+$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/profile', async route => {
      const method = route.request().method()
      if (method === 'PATCH') writes++
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      if ((method === 'GET' && malformedRead) || (method === 'PATCH' && malformedWrite)) {
        await route.fulfill({ status: 200, contentType: 'text/html', body: '<html>MNEME_PRIVATE_PROXY_BODY</html>' })
      } else await route.fulfill({ response })
    })
    await page.goto('/profile')
    await expect(page.locator('.profile-page [role="alert"]')).toContainText(formatError)
    await expect(page.getByRole('button', { name: '保存资料', exact: true })).toHaveCount(0)
    expect(await page.locator('body').innerText()).not.toContain('MNEME_PRIVATE_PROXY_BODY')
    malformedRead = false
    await page.locator('.profile-page').getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await page.getByRole('textbox', { name: '昵称', exact: true }).fill(`REST QA ${suffix.slice(0, 8)}`)
    await page.getByRole('button', { name: '保存资料', exact: true }).click()
    await expect(page.locator('.profile-page [role="alert"]')).toContainText(formatError)
    await expect(page.getByText('个人资料已保存', { exact: true })).toHaveCount(0)
    // The server committed the PATCH. An unreadable receipt must not cause an
    // automatic repeat of a mutation whose outcome is unknown to the client.
    expect(writes).toBe(1)
    expect((await api('get', '/profile')).nickname).toBe(`REST QA ${suffix.slice(0, 8)}`)
    malformedWrite = false
    await page.reload()
    await expect(page.getByRole('textbox', { name: '昵称', exact: true })).toHaveValue(`REST QA ${suffix.slice(0, 8)}`)
    expect(writes).toBe(1)
    await page.getByRole('textbox', { name: '昵称', exact: true }).fill('REST verified')
    await page.getByRole('button', { name: '保存资料', exact: true }).click()
    await expect(page.getByText('个人资料已保存', { exact: true })).toBeVisible()
    expect(writes).toBe(2)
    await page.screenshot({ path: testInfo.outputPath('rest-result-profile.png'), fullPage: false })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.goto('/settings')
    await expect(page.getByRole('form', { name: '个人模型服务', exact: true })).toBeVisible()
    await expect(page.getByText('正在读取服务状态…', { exact: true })).toHaveCount(0)
    await expect(page.getByText(formatError, { exact: true })).toHaveCount(0)
    const health = await page.request.get('/api/v1/health/config')
    expect(health.status()).toBe(200)
    const bare = await health.json()
    expect(bare).not.toHaveProperty('code')
    expect(bare.service).toBe('mneme-python-agent')
    expect(bare).toHaveProperty('storage')
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    // A registration timeout does not prove the transaction was rolled back.
    // Recover only this test's random account, then use the normal deletion Saga.
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') {
      account = await api('post', '/auth/login', { username, password })
    }
    if (account) {
      await page.close()
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
    }
  }
})
