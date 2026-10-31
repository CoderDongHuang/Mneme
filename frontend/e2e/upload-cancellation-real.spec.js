import { expect, test } from '@playwright/test'
import process from 'node:process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、MySQL 和解析服务')
test.setTimeout(180000)

test('真实限速上传取消、同批次继续和已提交回执确认', async ({ page }, testInfo) => {
  let registered = false
  let releaseResponse
  const evidence = { base_url: testInfo.project.use.baseURL || process.env.MNEME_E2E_BASE_URL, viewport: testInfo.project.use.viewport }
  async function api(method, path, options = {}) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const response = await page.request[method]('/api/v1' + path, options)
      if (response.status() === 429) {
        await page.waitForTimeout(Math.min(60000, Math.max(1000, Number(response.headers()['retry-after'] || 5) * 1000)))
        continue
      }
      const body = await response.json()
      expect(body.code, `${method} ${path}`).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    const auth = await api('post', '/auth/register', { data: { username: `uploadqa_${suffix.slice(0, 12)}`, password: `UploadQA!${suffix}` } })
    registered = true
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Upload cancellation QA', description: 'Temporary regression data' } })
    await page.goto('/knowledge')
    await expect(page.locator('.knowledge-library-bar select')).toHaveValue(String(kb.id))

    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Network.enable')
    let uploadRequest
    cdp.on('Network.requestWillBeSent', event => {
      if (new URL(event.request.url).pathname === '/api/v1/knowledge/document/upload' && !uploadRequest) uploadRequest = event.requestId
    })
    const aborted = new Promise(resolve => cdp.on('Network.loadingFailed', event => {
      if (event.requestId === uploadRequest) resolve(event)
    }))
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: 32 * 1024 })
    await page.locator('input[type=file][multiple]').setInputFiles([
      { name: 'cancel-large.txt', mimeType: 'text/plain', buffer: Buffer.alloc(4 * 1024 * 1024, 'a') },
      { name: 'continue-next.txt', mimeType: 'text/plain', buffer: Buffer.from('The second file continues after cancellation.') },
    ])
    const large = page.locator('.upload-queue-item').filter({ hasText: 'cancel-large.txt' })
    await expect(large).toHaveClass(/uploading/)
    await expect.poll(() => uploadRequest).toBeTruthy()
    await large.getByRole('button', { name: '取消上传', exact: true }).click()
    const failure = await aborted
    expect(failure.canceled).toBe(true)
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
    await expect(large).toHaveClass(/cancelled/)
    const next = page.locator('.upload-queue-item').filter({ hasText: 'continue-next.txt' })
    await expect(next).toHaveClass(/submitted/, { timeout: 30000 })
    const queue = await page.evaluate(() => JSON.parse(localStorage.getItem(`mneme.uploadQueue.${JSON.parse(localStorage.getItem('mneme_auth')).userId}`)))
    const cancelled = queue.find(item => item.name === 'cancel-large.txt')
    expect((await api('post', `/knowledge/document/uploads/${cancelled.requestId}/cancel?kbId=${kb.id}`)).status).toBe('cancelled')
    const docs = await api('get', `/knowledge/base/${kb.id}/documents`)
    expect(docs.map(document => document.fileName)).toEqual(['continue-next.txt'])
    evidence.in_flight_request_aborted = true
    evidence.server_confirmed_cancelled = true
    evidence.batch_continued = true

    let resolveCommitted
    const committed = new Promise(resolve => { resolveCommitted = resolve })
    const release = new Promise(resolve => { releaseResponse = resolve })
    await page.route('**/api/v1/knowledge/document/upload', async route => {
      const response = await route.fetch()
      const body = await response.json()
      resolveCommitted(body)
      await release
      await route.fulfill({ response }).catch(() => {}) // browser may already have aborted
    })
    await page.locator('input[type=file][multiple]').setInputFiles({ name: 'already-committed.txt', mimeType: 'text/plain', buffer: Buffer.from('The server commits before the response reaches the browser.') })
    const body = await committed
    expect(body.code).toBe(200)
    const committedRow = page.locator('.upload-queue-item').filter({ hasText: 'already-committed.txt' })
    await committedRow.getByRole('button', { name: '取消上传', exact: true }).click()
    await expect(committedRow).toHaveClass(/submitted/, { timeout: 30000 })
    await expect(committedRow.getByRole('link', { name: '任务中心', exact: true })).toHaveAttribute('href', '/tasks')
    await expect(committedRow.getByRole('button', { name: '取消上传', exact: true })).toHaveCount(0)
    const actual = await api('get', `/knowledge/document/${body.data.id}/status`)
    expect(actual.parseTaskId).toBeTruthy()
    expect(actual.status).not.toBe('cancelled')
    releaseResponse()
    await page.unroute('**/api/v1/knowledge/document/upload')
    await page.reload()
    await expect(page.locator('.upload-queue-item.submitted').filter({ hasText: 'already-committed.txt' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    evidence.committed_response_loss_reconciled = true
    evidence.reload_persisted = true
    await testInfo.attach('upload-cancellation.json', { body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: 'application/json' })
    await page.screenshot({ path: testInfo.outputPath('upload-cancellation.png'), fullPage: true })
  } finally {
    releaseResponse?.()
    if (registered) await api('delete', '/profile/account')
  }
})
