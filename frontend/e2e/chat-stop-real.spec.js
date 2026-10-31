import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_STREAM_QA_FAULTS !== 'true', '需要真实服务与隔离模型流测试')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实主动停止和无 Token 停止关闭上游，浏览器断流保持独立终态', async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  const agent = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(agent).toMatch(/^[a-f0-9]+$/)
  const python = (code, ...args) => execFileSync('docker', ['exec', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30_000 }).trim().split('\n').at(-1)
  async function api(method, path, body) {
    const response = await page.request[method]('/api/v1' + path, body === undefined ? {} : { data: body })
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBe(true)
    const result = await response.json()
    expect(result.code).toBe(200)
    return result.data
  }
  async function restart() {
    execFileSync('docker', ['restart', agent], { timeout: 30_000, stdio: 'pipe' })
    await expect.poll(async () => {
      try { return (await page.request.get('http://127.0.0.1:8001/health/ready', { timeout: 3000 })).ok() } catch { return false }
    }, { timeout: 60_000, intervals: [1000] }).toBe(true)
  }
  let account, folder
  try {
    const suffix = randomUUID().replaceAll('-', '')
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request.post('/api/v1/auth/register', { data: { username: `stopqa_${suffix.slice(0, 12)}`, password: `StreamQA!${suffix}` } })
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
    const sessions = []
    for (const mode of ['partial', 'silent', 'partial']) sessions.push({ ...(await api('post', '/sessions', { title: `Stream ${mode} QA` })), mode })
    const scope = { user: String(account.userId), sessions: Object.fromEntries(sessions.map(s => [String(s.id), s.mode])) }
    const fixture = fs.readFileSync('../test-fixtures/chat-stream-probe.py', 'utf8')
    folder = python(`import json,sys,tempfile\nfrom pathlib import Path\nroot=Path(tempfile.mkdtemp(prefix='mneme-stream-qa-'))\nmodule=Path('/app/app/api/chat_stream.py')\n(root/'original').write_bytes(module.read_bytes())\n(root/'scope.json').write_text(sys.argv[1])\n(root/'probe.py').write_text(sys.argv[2])\nsuffix=('\\nfrom pathlib import Path as _QaPath\\n_qa_root = _QaPath('+repr(str(root))+')\\nexec(compile((_qa_root / "probe.py").read_text(), str(_qa_root / "probe.py"), "exec"), globals())\\n').encode()\n(root/'suffix').write_bytes(suffix)\nmodule.write_bytes((root/'original').read_bytes()+suffix)\nprint(str(root))`, JSON.stringify(scope), fixture)
    expect(folder).toMatch(/^\/tmp\/mneme-stream-qa-/)
    await restart()
    const marker = session => JSON.parse(python(`import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1])/(sys.argv[2]+'.json')\nprint(p.read_text() if p.exists() else '{}')`, folder, session.id))
    const history = session => api('get', `/sessions/${session.id}/messages`)
    for (let index = 0; index < sessions.length; index++) {
      const session = sessions[index]
      await page.goto(`/chat?session=${session.id}`)
      const input = page.getByRole('textbox', { name: '向忆知提问...' })
      await expect(page.locator('.chat-heading')).toContainText(session.title)
      await input.fill('Hello, please continue this conversation.')
      const responseReady = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/chat/stream', { timeout: 10_000 })
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const streamResponse = await responseReady
      expect(streamResponse.ok()).toBe(true)
      expect(streamResponse.headers()['content-type']).toContain('text/event-stream')
      expect(streamResponse.headers()['content-encoding']).toBeUndefined()
      await testInfo.attach(`stream-${index}-transport.json`, { body: JSON.stringify({
        contentType: streamResponse.headers()['content-type'], encoding: streamResponse.headers()['content-encoding'] || 'identity',
      }), contentType: 'application/json' })
      await expect.poll(() => !!marker(session).started, { timeout: 30_000 }).toBe(true)
      if (session.mode === 'partial') await expect(page.locator('.message-assistant')).toContainText('Stream QA partial answer')
      if (index < 2) {
        await page.getByRole('button', { name: '停止生成', exact: true }).click()
        await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
        await expect(page.locator('.message-assistant')).toContainText(session.mode === 'partial' ? '已停止 · 保留部分回答' : '已停止生成')
      } else await page.reload()
      await expect.poll(() => !!marker(session).closed, { timeout: 5000, intervals: [100, 200] }).toBe(true)
      await expect.poll(async () => (await history(session)).find(m => m.role === 'assistant')?.status, { timeout: 5000 }).toBe(index < 2 ? 'stopped' : 'failed')
      const saved = (await history(session)).find(m => m.role === 'assistant')
      expect(saved.errorCode).toBe(index < 2 ? 'USER_STOPPED' : 'CLIENT_DISCONNECTED')
      expect(saved.content).toBe(session.mode === 'partial' ? 'Stream QA partial answer' : '')
      if (index < 2) {
        // The persisted stop is idempotent and an obsolete generation is rejected.
        expect(await api('post', '/chat/stop', { session_id: String(session.id), request_id: saved.requestId, answer_generation: saved.answerGeneration })).toEqual({ status: 'stopped' })
        const stale = await page.request.post('/api/v1/chat/stop', { data: { session_id: String(session.id), request_id: saved.requestId, answer_generation: saved.answerGeneration + 1 } })
        expect(stale.status()).toBe(409)
      }
      // Reload starts a real history request. Assert its response separately from
      // the render deadline, so a slow HTTP request is not misreported as lost data.
      const historyReady = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/sessions/${session.id}/messages`, { timeout: 10_000 })
      await page.reload()
      const historyResponse = await historyReady
      expect(historyResponse.ok()).toBe(true)
      await testInfo.attach(`stream-${index}-reload.json`, { body: JSON.stringify({
        status: historyResponse.status(), requestDurationMs: historyResponse.request().timing().responseEnd,
      }), contentType: 'application/json' })
      await expect(page.locator('.message-assistant')).toContainText(session.mode === 'partial' ? 'Stream QA partial answer' : '已停止生成')
      if (index === 2) await expect(page.locator('.message-assistant [role="alert"]')).toContainText('连接已中断，请重试 · 已保留部分回答')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`stream-${index}.png`), fullPage: true, animations: 'disabled' })
    }
    await testInfo.attach('stream-cleanup.json', { body: JSON.stringify({ stop: true, no_token_stop: true, disconnect: true, upstream_closed: true }), contentType: 'application/json' })
  } finally {
    // Restore before deleting the test user. No fault hook survives the test.
    if (folder) {
      python(`import sys,shutil\nfrom pathlib import Path\nroot=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-stream-qa-')\nmodule=Path('/app/app/api/chat_stream.py')\noriginal=(root/'original').read_bytes()\nassert module.read_bytes()==original+(root/'suffix').read_bytes()\nmodule.write_bytes(original)\nassert module.read_bytes()==original\nshutil.rmtree(root)\nprint('restored')`, folder)
      await restart()
    }
    if (account) await api('delete', '/profile/account')
  }
})
