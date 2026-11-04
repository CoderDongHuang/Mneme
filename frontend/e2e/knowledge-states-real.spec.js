import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { Buffer } from 'node:buffer'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、MySQL 和 Agent')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('知识库独立重试、筛选空状态与真实删除回执不受轮询故障覆盖', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const username = `kbqa_${suffix.slice(0, 12)}`, password = `KnowledgeQA!${suffix}`
  let account, cleanup, failBases = true, failDocuments = true, failActivity = true, deleteCount = 0
  let holdDocuments = false, releaseDocuments, documentPollHeld = false
  let invalidIndexReport = true, invalidPreview = true
  const heldDocuments = new Promise(resolve => { releaseDocuments = resolve })
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
      return body.data
    }
  }
  try {
    account = await api('post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL,
      storageState: await page.context().storageState(), timeout: 45000 })
    const base = await api('post', '/knowledge/base', { name: 'Knowledge state QA', description: '' })
    const upload = await page.request.post('/api/v1/knowledge/document/upload', { multipart: {
      kbId: String(base.id), requestId: randomUUID(),
      file: { name: 'knowledge-state-qa.txt', mimeType: 'text/plain', buffer: Buffer.from('A knowledge library organizes study documents. This is synthetic regression test content.') },
    }, timeout: 45000 })
    expect(upload.status()).toBe(200)
    const receipt = await upload.json(); expect(receipt.code).toBe(200)
    const documentId = receipt.data.id
    await expect.poll(async () => (await api('get', `/knowledge/document/${documentId}/status`)).status,
      { timeout: 90000, intervals: [1000, 2000] }).toMatch(/^(ready|partial)$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    // Isolate notification-triggered refreshes; their coalescing and cancellation
    // are covered in hook tests, while all successful GETs use actual services.
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/knowledge/base/list', route => failBases ? route.abort('failed') : route.continue())
    await page.route(`**/api/v1/knowledge/base/${base.id}/documents`, async route => {
      if (failDocuments) return route.abort('failed')
      if (holdDocuments) { documentPollHeld = true; await heldDocuments }
      if (invalidIndexReport) {
        const response = await route.fetch(), body = await response.json()
        expect(body.code).toBe(200)
        body.data = body.data.map(doc => ({ ...doc, parseReport: 'null' }))
        return route.fulfill({ response, json: body })
      }
      await route.continue()
    })
    await page.route(`**/api/v1/workspace/documents/${documentId}/preview`, async route => {
      if (!invalidPreview) return route.continue()
      const response = await route.fetch(), body = await response.json()
      expect(body.code).toBe(200)
      // Corrupt only the browser's copy of a real response, never stored data.
      body.data.parse_report.pages = [{ page: 1, blocks: [{ content: {} }] }]
      await route.fulfill({ response, json: body })
    })
    await page.route('**/api/v1/notifications', route => failActivity ? route.abort('failed') : route.continue())
    await page.route(`**/api/v1/knowledge/document/${documentId}`, async route => {
      if (route.request().method() === 'DELETE') { deleteCount++; failDocuments = true }
      await route.continue()
    })
    await page.goto('/knowledge')
    const bases = page.getByRole('region', { name: '资料库读取', exact: true })
    const activity = page.getByRole('region', { name: '最近活动', exact: true })
    await expect(bases.getByRole('alert')).toContainText('资料库加载失败')
    await expect(page.getByText('建立第一个资料库', { exact: true })).toHaveCount(0)
    await expect(activity.getByRole('alert')).toContainText('最近活动加载失败')
    await expect(activity.getByText('暂无处理活动', { exact: true })).toHaveCount(0)
    failBases = false
    await bases.getByRole('button', { name: '重试 / Retry' }).click()
    const documents = page.getByRole('region', { name: '文档读取', exact: true })
    await expect(documents.getByRole('alert')).toContainText('文档列表加载失败')
    await expect(page.getByText('这里还没有资料', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '导入资料', exact: true })).toBeDisabled()
    failDocuments = false
    await documents.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(page.getByRole('button', { name: 'knowledge-state-qa.txt', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'knowledge-state-qa.txt', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: '解析报告格式无效，请重新解析' })).toBeVisible()
    const previewError = page.getByRole('alert').filter({ hasText: '文档预览格式无效，请重试或重新解析' })
    await expect(previewError).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('knowledge-preview-invalid.png'), fullPage: false })
    invalidPreview = false
    await previewError.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(previewError).toHaveCount(0)
    await page.getByRole('button', { name: '解析结构', exact: true }).click()
    await expect(page.getByRole('textbox', { name: '资料标签', exact: true })).toBeVisible()
    await page.locator('.parse-preview summary').filter({ hasText: '抽取文本' }).first().click()
    await expect(page.getByText('A knowledge library organizes study documents.', { exact: false }).first()).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('knowledge-preview-recovered.png'), fullPage: false })
    await page.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    invalidIndexReport = false
    // Hold an actual poll in flight: filtering must still use the last verified
    // snapshot while writes remain unavailable. Do not rely on a fast GET.
    holdDocuments = true
    await expect.poll(() => documentPollHeld).toBe(true)
    await expect(documents).toHaveAttribute('aria-busy', 'true')
    const search = page.getByRole('textbox', { name: '筛选文档', exact: true })
    await search.fill('no-match')
    await expect(search).toHaveValue('no-match')
    await expect(page.getByText('没有符合筛选条件的资料', { exact: true })).toBeVisible()
    await expect(page.getByText('这里还没有资料', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '导入资料', exact: true })).toBeDisabled()
    await page.screenshot({ path: testInfo.outputPath('knowledge-filter-refresh.png'), fullPage: false })
    holdDocuments = false
    releaseDocuments()
    await search.fill('')
    await expect(documents).toHaveAttribute('aria-busy', 'false')
    failActivity = false
    await activity.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(activity.getByRole('alert')).toHaveCount(0)
    page.on('dialog', dialog => dialog.accept())
    await page.locator('summary[aria-label="文档操作：knowledge-state-qa.txt"]').click()
    await page.getByRole('button', { name: '删除文档', exact: true }).click()
    await expect(page.getByText('删除任务已提交，最终结果请查看任务中心。', { exact: true })).toBeVisible()
    await expect(documents.getByRole('alert')).toContainText('文档列表加载失败')
    expect(deleteCount).toBe(1)
    await expect(page.getByRole('button', { name: '导入资料', exact: true })).toBeDisabled()
    await page.screenshot({ path: testInfo.outputPath('knowledge-state.png'), fullPage: false })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await expect.poll(() => sql(`SELECT COUNT(*) FROM knowledge_document WHERE id=${documentId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
    failDocuments = false
    // The serial poll can already recover before a retry button is clicked.
    // Manual retries were verified above; now verify automatic recovery.
    await expect(page.getByText('这里还没有资料', { exact: true })).toBeVisible()
    await expect(page.getByText('删除任务已提交，最终结果请查看任务中心。', { exact: true })).toBeVisible()
    expect(deleteCount).toBe(1)
  } catch (error) {
    // Keep limited synthetic-test state before cleanup closes the page. Never
    // attach storageState, credentials, service bodies or arbitrary page text.
    if (!page.isClosed()) {
      const state = await page.evaluate(() => ({
        search: document.querySelector('input[aria-label="筛选文档"]')?.value,
        reads: [...document.querySelectorAll('section[aria-busy]')].map(node => ({
          label: node.getAttribute('aria-label'), busy: node.getAttribute('aria-busy'),
          alerts: node.querySelectorAll('[role="alert"]').length,
        })),
        rows: document.querySelectorAll('.document-row').length,
        empty: [...document.querySelectorAll('.documents-empty strong')].map(node => node.textContent),
      })).catch(() => ({ unavailable: true }))
      await testInfo.attach('knowledge-read-state', { body: JSON.stringify(state), contentType: 'application/json' })
    }
    throw error
  } finally {
    releaseDocuments()
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api('post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL,
        storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        const response = await cleanup.delete('/api/v1/profile/account')
        expect(response.status()).toBe(200)
        expect((await response.json()).code).toBe(200)
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
