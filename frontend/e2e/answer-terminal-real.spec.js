import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实完成事件到达时答案引用已落库，立即断流重放及刷新保持一致', async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  let account
  async function api(method, path, body) {
    const response = await page.request[method]('/api/v1' + path, body === undefined ? {} : { data: body })
    expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBe(true)
    const payload = await response.json()
    expect(payload.code).toBe(200)
    return payload.data
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request.post('/api/v1/auth/register', { data: { username: `ansqa_${suffix.slice(0, 12)}`, password: `AnswerQA!${suffix}` } })
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
    const kb = await api('post', '/knowledge/base', { name: 'Answer terminal QA' })
    const upload = await page.request.post('/api/v1/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'answer-evidence.txt', mimeType: 'text/plain', buffer: fs.readFileSync('../test-fixtures/rag-fixture.txt') },
    } })
    expect(upload.ok()).toBe(true)
    const document = (await upload.json()).data
    await expect.poll(async () => (await api('get', `/knowledge/document/${document.id}/status`)).status,
      { timeout: 90_000, intervals: [2000] }).toBe('ready')
    const session = await api('post', '/sessions', { title: 'Answer terminal QA' })
    await page.goto('/chat')
    const request = { session_id: String(session.id), request_id: randomUUID(), message: '星桥计划的核心识别码是什么？请引用资料。', knowledge_base_ids: [String(kb.id)] }
    const result = await page.evaluate(async request => {
      async function stream() {
        const response = await fetch('/api/v1/chat/stream', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) })
        if (!response.ok) throw new Error(`stream status ${response.status}`)
        const reader = response.body.getReader()
        const decoder = new TextDecoder(); let buffer = ''; let answer = ''; let sources = []
        try {
          while (true) {
            const next = await reader.read()
            if (next.done) throw new Error('EOF before done')
            buffer += decoder.decode(next.value, { stream: true })
            let end
            while ((end = buffer.indexOf('\n\n')) >= 0) {
              const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2)
              const type = frame.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
              const data = JSON.parse(frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n'))
              if (type === 'error') throw new Error('unexpected stream error')
              if (type === 'token') answer += data.content
              if (type === 'meta') sources = data.sources
              if (type === 'done') {
                // Cancel immediately, exactly as the actual UI does. No delay/poll to hide late commits.
                await reader.cancel()
                const history = await fetch(`/api/v1/sessions/${request.session_id}/messages`, { credentials: 'include' })
                if (!history.ok) throw new Error(`history status ${history.status}`)
                return { answer, sources, history: (await history.json()).data, replayed: data.replayed === true }
              }
            }
          }
        } finally { reader.releaseLock() }
      }
      return { first: await stream(), replay: await stream() }
    }, request)
    expect(result.first.answer).toContain('QZ-7294')
    expect(result.first.sources.length).toBeGreaterThan(0)
    expect(result.first.history).toHaveLength(2)
    const saved = result.first.history.find(message => message.role === 'assistant')
    expect(saved).toMatchObject({ status: 'completed', errorCode: null, content: result.first.answer, answerGeneration: 1 })
    expect(JSON.parse(saved.sourcesJson)).toEqual(result.first.sources)
    expect(result.replay.answer).toBe(result.first.answer)
    expect(result.replay.sources).toEqual(result.first.sources)
    expect(result.replay.replayed).toBe(true)
    expect(result.replay.history).toEqual(result.first.history)
    const syncReplay = await api('post', '/chat', request)
    expect(syncReplay.answer).toBe(result.first.answer)
    expect(syncReplay.sources).toEqual(result.first.sources)
    await page.reload()
    const history = page.getByRole('button', { name: '切换会话栏' })
    if (await history.getAttribute('aria-expanded') === 'false') await history.click()
    await page.getByRole('button', { name: /打开对话：Answer terminal QA/ }).click()
    await expect(page.locator('.message-assistant')).toHaveCount(1)
    await expect(page.locator('.message-assistant')).toContainText('QZ-7294')
    await expect(page.getByRole('button', { name: /查看 \d+ 条资料依据/ })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('answer-persisted.png'), fullPage: true })
    await testInfo.attach('answer-terminal.json', { body: JSON.stringify({ completed_at_done: true, immediate_cancel: true, sources_persisted: true, replay_unchanged: true, viewport: testInfo.project.use.viewport }), contentType: 'application/json' })
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
