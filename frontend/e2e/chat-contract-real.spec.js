import { expect, test } from '@playwright/test'
import { execFileSync, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_STREAM_QA_FAULTS !== 'true', '需要真实服务和显式隔离故障注入')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实网关拒绝非法上游帧并关闭模型，刷新保留失败原因和合法部分回答', async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  const agent = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(agent).toMatch(/^[a-f0-9]+$/)
  const python = (code, ...args) => execFileSync('docker', ['exec', '--user', '0', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30_000 }).trim().split('\n').at(-1)
  const owner = JSON.parse(execFileSync('docker', ['exec', agent, 'python', '-c', 'import os,json; print(json.dumps([os.getuid(),os.getgid()]))'], { encoding: 'utf8' }))
  const suffix = randomUUID().replaceAll('-', '')
  const canary = `MNEME_PRIVATE_FRAME_${suffix}`
  const logStart = new Date().toISOString()
  let account, folder
  async function api(method, path, body) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, body === undefined ? {} : { data: body })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const payload = await response.json(); expect(payload.code).toBe(200)
      return payload.data
    }
    throw new Error('Rate limit did not recover')
  }
  async function restart() {
    execFileSync('docker', ['restart', agent], { timeout: 40_000, stdio: 'pipe' })
    await expect.poll(async () => {
      try { return (await page.request.get('http://127.0.0.1:8001/health/ready', { timeout: 3000 })).ok() } catch { return false }
    }, { timeout: 60_000, intervals: [1000] }).toBe(true)
  }
  try {
    account = await api('post', '/auth/register', { username: `contractqa_${suffix.slice(0, 10)}`, password: `ContractQA!${suffix}` })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    // Observe the real response before the production client cancels its reader
    // on error. Chromium may discard the CDP body of an aborted fetch. This
    // clone consumes the same wire bytes without replacing requests or frames.
    await page.addInitScript(() => {
      const fetch = window.fetch.bind(window)
      window.fetch = async (...args) => {
        const response = await fetch(...args)
        if (new URL(response.url).pathname === '/api/v1/chat/stream') window.__mnemeContractWire = response.clone().text()
        return response
      }
    })
    const sessions = []
    for (const mode of ['type', 'json']) sessions.push({ ...(await api('post', '/sessions', { title: `Contract ${mode} QA` })), mode })
    const scope = { user: String(account.userId), sessions: Object.fromEntries(sessions.map(s => [String(s.id), s.mode])), canary }
    folder = python("import tempfile\nprint(tempfile.mkdtemp(prefix='mneme-contract-qa-'))")
    expect(folder).toMatch(/^\/tmp\/mneme-contract-qa-/)
    python(`import os,json,sys
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-contract-qa-')
module=Path('/app/app/api/chat_stream.py')
(root/'original').write_bytes(module.read_bytes())
(root/'scope.json').write_text(sys.argv[2])
(root/'probe.py').write_text(sys.argv[3])
suffix=('\\nfrom pathlib import Path as _QaPath\\n_qa_root = _QaPath('+repr(str(root))+')\\nexec(compile((_qa_root / "probe.py").read_text(), str(_qa_root / "probe.py"), "exec"), globals())\\n').encode()
(root/'suffix').write_bytes(suffix)
os.chown(root,*json.loads(sys.argv[4]))
module.write_bytes((root/'original').read_bytes()+suffix)
print('installed')`, folder, JSON.stringify(scope), fs.readFileSync('../test-fixtures/chat-contract-probe.py', 'utf8'), JSON.stringify(owner))
    await restart()
    for (const session of sessions) {
      await page.goto(`/chat?session=${session.id}`)
      await expect(page.locator('.chat-heading')).toContainText(session.title)
      await page.getByRole('textbox', { name: '向忆知提问...' }).fill('hello')
      const responseReady = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/chat/stream')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const response = await responseReady
      expect(response.ok()).toBe(true)
      await expect(page.locator('.message-assistant [role="alert"]')).toContainText('回答流格式异常，请重试')
      const wire = await page.evaluate(() => window.__mnemeContractWire)
      expect(wire).toContain('INVALID_CHAT_EVENT')
      expect(wire).not.toContain('event: done')
      expect(wire).not.toContain(canary)
      expect(wire).not.toMatch(/"content"\s*:\s*123\b/)
      const saved = (await api('get', `/sessions/${session.id}/messages`)).find(m => m.role === 'assistant')
      expect(saved).toMatchObject({ status: 'failed', errorCode: 'INVALID_CHAT_EVENT', content: 'Contract QA retained partial answer' })
      await expect.poll(() => python(`import sys\nfrom pathlib import Path\np=Path(sys.argv[1])/(sys.argv[2]+'.json')\nprint(p.read_text() if p.exists() else '{}')`, folder, session.id), { timeout: 5000 }).toBe('{"closed": true}')
      await page.reload()
      await expect(page.locator('.message-assistant [role="alert"]')).toContainText('回答流格式异常，请重试 · 已保留部分回答')
      await expect(page.locator('.message-assistant')).toContainText('Contract QA retained partial answer')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`contract-${session.mode}.png`), fullPage: true, animations: 'disabled' })
    }
    for (const service of ['python-agent', 'java-gateway']) {
      const id = execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
      const logs = spawnSync('docker', ['logs', '--since', logStart, id], { encoding: 'utf8' })
      expect(logs.status).toBe(0)
      expect(logs.stdout + logs.stderr).not.toContain(canary)
    }
  } finally {
    if (folder) {
      python(`import sys,shutil
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-contract-qa-')
module=Path('/app/app/api/chat_stream.py')
if (root/'original').exists():
 original=(root/'original').read_bytes(); current=module.read_bytes()
 assert current==original or ((root/'suffix').exists() and current==original+(root/'suffix').read_bytes())
 module.write_bytes(original); assert module.read_bytes()==original
shutil.rmtree(root)
print('restored')`, folder)
      await restart()
    }
    if (account) await api('delete', '/profile/account')
  }
})
