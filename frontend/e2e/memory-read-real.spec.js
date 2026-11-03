import { expect, test } from '@playwright/test'
import { execFileSync, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_MEMORY_QA_FAULTS !== 'true', '需要真实服务和显式隔离故障注入')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实记忆读取故障拒绝覆盖旧数据，表单保留且恢复后可重试', async ({ page }, testInfo) => {
  test.setTimeout(240_000)
  const agent = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(agent).toMatch(/^[a-f0-9]+$/)
  const python = (code, ...args) => execFileSync('docker', ['exec', '--user', '0', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30_000 }).trim().split('\n').at(-1)
  const owner = JSON.parse(execFileSync('docker', ['exec', agent, 'python', '-c', 'import os,json; print(json.dumps([os.getuid(),os.getgid()]))'], { encoding: 'utf8' }))
  const suffix = randomUUID().replaceAll('-', '')
  const canary = `MNEME_PRIVATE_MEMORY_${suffix}`
  const logStart = new Date().toISOString()
  const message = '长期记忆暂时无法读取，请稍后重试'
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
  async function snapshot() {
    const data = await api('get', '/workspace/memories')
    const versions = await Promise.all(data.memories.map(async item => [item.id, await api('get', `/workspace/memories/${item.id}/versions`)]))
    return { memories: data.memories.toSorted((a, b) => a.id.localeCompare(b.id)), versions: versions.toSorted((a, b) => a[0].localeCompare(b[0])) }
  }
  function fault(enabled) {
    python(`import sys\nfrom pathlib import Path\np=Path(sys.argv[1])/'fault'\np.touch() if sys.argv[2]=='true' else p.unlink(missing_ok=True)`, folder, enabled)
  }
  try {
    account = await api('post', '/auth/register', { username: `memreadqa_${suffix.slice(0, 10)}`, password: `MemoryQA!${suffix}` })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await api('post', '/memory/write', { category: 'weak_point', content: 'QA original weak point', topic: 'QA topic' })
    await api('post', '/memory/write', { category: 'progress', content: 'QA original/section one' })
    const before = await snapshot()
    expect(before.memories).toHaveLength(2)
    folder = python("import tempfile\nprint(tempfile.mkdtemp(prefix='mneme-memory-read-qa-'))")
    expect(folder).toMatch(/^\/tmp\/mneme-memory-read-qa-/)
    python(`import os,json,sys
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-memory-read-qa-')
module=Path('/app/app/memory/memory_store.py')
(root/'original').write_bytes(module.read_bytes())
(root/'scope.json').write_text(sys.argv[2])
(root/'probe.py').write_text(sys.argv[3])
suffix=('\\nfrom pathlib import Path as _QaPath\\n_qa_root = _QaPath('+repr(str(root))+')\\nexec(compile((_qa_root / "probe.py").read_text(), str(_qa_root / "probe.py"), "exec"), globals())\\n').encode()
(root/'suffix').write_bytes(suffix)
os.chown(root,*json.loads(sys.argv[4]))
module.write_bytes((root/'original').read_bytes()+suffix)
print('installed')`, folder, JSON.stringify({ user: String(account.userId), canary }), fs.readFileSync(new URL('../../test-fixtures/memory-read-probe.py', import.meta.url), 'utf8'), JSON.stringify(owner))
    await restart()
    fault(true)
    const response = await page.request.get('/api/v1/memory')
    expect(response.status()).toBe(503)
    expect(await response.json()).toMatchObject({ code: 503, message })
    expect(await response.text()).not.toContain(canary)
    await page.goto('/memory')
    await expect(page.getByRole('button', { name: '添加记忆', exact: true })).toBeEnabled()
    await expect(page.locator('.reference-table')).toContainText('QA original weak point')
    for (const category of ['weak_point', 'progress']) {
      await page.getByRole('button', { name: '添加记忆', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '添加学习记忆' })
      await dialog.getByLabel('类型').selectOption(category)
      await dialog.getByLabel('主题', { exact: true }).fill('QA topic')
      const content = category === 'progress' ? 'QA recovered/section two' : 'QA reinforce existing topic'
      await dialog.getByLabel('内容', { exact: true }).fill(content)
      const failed = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/memory/write')
      await dialog.getByRole('button', { name: '保存记忆', exact: true }).click()
      expect((await failed).status()).toBe(503)
      await expect(dialog.getByRole('alert')).toContainText(message)
      await expect(dialog.getByLabel('内容', { exact: true })).toHaveValue(content)
      await expect(dialog.getByLabel('主题', { exact: true })).toHaveValue('QA topic')
      expect(await snapshot()).toEqual(before)
      await page.screenshot({ path: testInfo.outputPath(`failure-${category}.png`), fullPage: true, animations: 'disabled' })
      if (category === 'weak_point') await dialog.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    }
    fault(false)
    const recovered = await api('get', '/memory')
    expect(recovered.weakPoints ?? recovered.weak_points).toHaveLength(1)
    expect(recovered.progress.content).toContain('QA original')
    expect(await snapshot()).toEqual(before)
    const dialog = page.getByRole('dialog', { name: '添加学习记忆' })
    await dialog.getByRole('button', { name: '保存记忆', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: '记忆已添加' })).toBeVisible()
    const after = await snapshot()
    expect(after.memories).toHaveLength(2)
    expect(after.memories.find(item => item.category === 'progress').content).toContain('QA recovered')
    expect(after.memories.find(item => item.category === 'weak_point')).toEqual(before.memories.find(item => item.category === 'weak_point'))
    await page.getByRole('button', { name: '添加记忆', exact: true }).click()
    const retryDialog = page.getByRole('dialog', { name: '添加学习记忆' })
    await retryDialog.getByLabel('类型').selectOption('weak_point')
    await retryDialog.getByLabel('主题', { exact: true }).fill('QA topic')
    await retryDialog.getByLabel('内容', { exact: true }).fill('QA reinforce existing topic')
    await retryDialog.getByRole('button', { name: '保存记忆', exact: true }).click()
    await expect(retryDialog).not.toBeVisible()
    const reinforced = await snapshot()
    expect(reinforced.memories).toHaveLength(2)
    const originalWeakPoint = before.memories.find(item => item.category === 'weak_point')
    expect(reinforced.memories.find(item => item.id === originalWeakPoint.id)).toMatchObject({
      content: originalWeakPoint.content, importance: originalWeakPoint.importance + 0.1,
    })
    await page.reload()
    await expect(page.locator('.reference-table')).toContainText('QA recovered')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('recovered.png'), fullPage: true, animations: 'disabled' })
    for (const service of ['python-agent', 'java-gateway']) {
      const id = execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--filter', service === 'python-agent' ? 'publish=8001' : 'publish=8080', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
      const logs = spawnSync('docker', ['logs', '--since', logStart, id], { encoding: 'utf8' })
      expect(logs.status).toBe(0)
      expect(logs.stdout + logs.stderr).not.toContain(canary)
    }
  } finally {
    if (folder) {
      python(`import sys,shutil
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-memory-read-qa-')
module=Path('/app/app/memory/memory_store.py')
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
