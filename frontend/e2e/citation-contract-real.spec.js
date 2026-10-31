import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实 PDF 同步、SSE、持久引用与重放采用同一数字坐标契约', async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  const schema = JSON.parse(fs.readFileSync('../contracts/chat-source.schema.json', 'utf8'))
  let account
  async function api(method, path, data) {
    const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
    expect(response.ok(), `${method} ${path}: HTTP ${response.status()}`).toBe(true)
    const payload = await response.json()
    expect(payload.code).toBe(200)
    return payload.data
  }
  function verifySources(sources, documentId) {
    expect(sources.length).toBeGreaterThan(0)
    for (const source of sources) {
      expect(Object.keys(source).sort()).toEqual(Object.keys(schema.properties).sort())
      expect(source.document_id).toBe(String(documentId))
      expect(source.document_name).toBe('citation-evidence.pdf')
      expect(source.chunk_content).toContain('QZ-7294')
      expect(source.visual_region).toHaveLength(4)
      expect(source.visual_region.every(Number.isFinite)).toBe(true)
      const [left, top, right, bottom] = source.visual_region
      expect(left >= 0 && left <= right && right <= 1 && top >= 0 && top <= bottom && bottom <= 1).toBe(true)
      expect(source.visual_page).toBeGreaterThan(0)
      expect(source.content_sha256).toMatch(/^[a-f0-9]{64}$/)
    }
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request.post('/api/v1/auth/register', { data: { username: `citeqa_${suffix.slice(0, 12)}`, password: `CitationQA!${suffix}` } })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.ok()).toBe(true)
      account = (await response.json()).data
      break
    }
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    const kb = await api('post', '/knowledge/base', { name: 'Citation contract QA' })
    const upload = await page.request.post('/api/v1/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'citation-evidence.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync('../test-fixtures/rag-fixture.pdf') },
    } })
    expect(upload.ok()).toBe(true)
    const document = (await upload.json()).data
    await expect.poll(async () => (await api('get', `/knowledge/document/${document.id}/status`)).status,
      { timeout: 90_000, intervals: [2000] }).toBe('ready')
    const session = await api('post', '/sessions', { title: 'Citation contract QA' })
    const message = { session_id: String(session.id), request_id: randomUUID(), message: '星桥计划的核心识别码是什么？请引用资料。', knowledge_base_ids: [String(kb.id)] }
    const sync = await api('post', '/chat', message)
    expect(sync.answer).toContain('QZ-7294')
    verifySources(sync.sources, document.id)
    await page.goto('/chat')
    const streamed = await page.evaluate(async request => {
      const response = await fetch('/api/v1/chat/stream', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''; let answer = ''; let sources
      try {
        while (true) {
          const next = await reader.read()
          if (next.done) throw new Error('EOF before done')
          buffer += decoder.decode(next.value, { stream: true })
          let end
          while ((end = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2)
            const name = frame.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
            if (!name) continue
            const data = JSON.parse(frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n'))
            if (name === 'error' || name === 'stopped') throw new Error(`Unexpected ${name}`)
            if (name === 'meta') sources = data.sources
            if (name === 'token') answer += data.content
            if (name === 'done') return { answer, sources, replayed: data.replayed === true }
          }
        }
      } finally { await reader.cancel(); reader.releaseLock() }
    }, { ...message, request_id: randomUUID() })
    expect(streamed.answer).toContain('QZ-7294')
    expect(streamed.replayed).toBe(false)
    verifySources(streamed.sources, document.id)
    const history = await api('get', `/sessions/${session.id}/messages`)
    const assistant = history.filter(item => item.role === 'assistant')
    expect(assistant).toHaveLength(2)
    expect(JSON.parse(assistant[0].sourcesJson)).toEqual(sync.sources)
    expect(JSON.parse(assistant[1].sourcesJson)).toEqual(streamed.sources)
    // Idempotent JSON replay uses the same stored citation representation.
    expect((await api('post', '/chat', message)).sources).toEqual(sync.sources)
    await page.reload()
    const historyToggle = page.getByRole('button', { name: '切换会话栏' })
    if (await historyToggle.getAttribute('aria-expanded') === 'false') await historyToggle.click()
    await page.getByRole('button', { name: /打开对话：Citation contract QA/ }).click()
    await expect(page.locator('.message-assistant')).toHaveCount(2)
    await page.getByRole('button', { name: /查看 \d+ 条资料依据/ }).last().click()
    await expect(page.locator('.source-drawer')).toContainText('citation-evidence.pdf')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('citation-contract.png'), fullPage: true, animations: 'disabled' })
    await testInfo.attach('citation-contract.json', { body: JSON.stringify({ numeric_rectangles: true, sync_and_sse: true, persisted_and_replayed: true, fields: Object.keys(schema.properties) }), contentType: 'application/json' })
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
