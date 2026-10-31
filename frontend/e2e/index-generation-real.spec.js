import { expect, test } from '@playwright/test'
import process from 'node:process'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_INDEX_QA_FAULTS !== 'true', '需要真实服务和隔离账号并发故障注入授权')

test('旧入库 worker 在租约检查后暂停，新解析完成后恢复仍不能改写索引', async ({ page }, testInfo) => {
  test.setTimeout(240000)
  const agents = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
  expect(agents).toHaveLength(1)
  const agent = agents[0]
  const python = (code, ...args) => execFileSync('docker', ['exec', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30000 }).trim().split('\n').at(-1)
  async function api(method, path, options = {}) {
    for (let attempt = 0; attempt < 4; attempt++) {
      const response = await page.request[method]('/api/v1' + path, options)
      const delay = Number(response.headers()['retry-after'])
      if (response.status() === 429 && delay > 0 && delay <= 60) {
        await page.waitForTimeout(delay * 1000 + 250)
        continue
      }
      expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy()
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Registration rate limit did not recover')
  }
  const unique = randomUUID().replaceAll('-', '')
  const auth = await api('post', '/auth/register', { data: { username: `genqa_${unique.slice(0, 12)}`, password: `GenerationQA!${unique}` } })
  const user = String(auth.userId)
  expect(user).toMatch(/^\d+$/)
  let folder
  try {
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Generation fencing QA' } })
    const doc = await api('post', '/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'generation.txt', mimeType: 'text/plain', buffer: Buffer.from('Original generation evidence before replacement.') },
    } })
    const status = () => api('get', `/knowledge/document/${doc.id}/status`)
    await expect.poll(async () => (await status()).status, { timeout: 60000 }).toBe('ready')
    const originalGeneration = JSON.parse((await status()).parseReport).index_generation
    // Exercise the actual cancellation cleanup HTTP boundary (the same one
    // used by Gateway's cancellation worker), then reparse via the public API.
    // No replacement of storage or HTTP responses is involved.
    const cancelled = python(`import json,sys,urllib.request,urllib.parse
from app.core.config import settings
user,kb,doc=sys.argv[1:]
url='http://127.0.0.1:8001/api/v1/knowledge/internal/cancelled-documents/'+doc+'?'+urllib.parse.urlencode({'user_id':user,'kb_id':kb})
request=urllib.request.Request(url,method='DELETE',headers={'X-Internal-Service-Token':settings.internal_service_token})
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=20) as response:
 print(json.dumps(json.load(response)))`, user, kb.id, `doc_${doc.id}`)
    expect(JSON.parse(cancelled).deleted_chunks).toBeGreaterThan(0)
    await api('post', `/knowledge/document/${doc.id}/reparse`)
    await expect.poll(async () => {
      const current = await status()
      return current.status === 'ready' && JSON.parse(current.parseReport).index_generation > originalGeneration
    }, { timeout: 60000 }).toBe(true)
    const firstGeneration = JSON.parse((await status()).parseReport).index_generation
    expect(firstGeneration).toBeGreaterThan(0)
    // A separate real ingestion process models an abandoned worker reservation.
    // Its live Redis lease remains valid while it is paused immediately after
    // check_cancelled and before the durable write guard. No web API is mocked.
    const worker = `import json,sys,time,uuid
from pathlib import Path
from contextlib import contextmanager
from app.knowledge import ingestion
from app.knowledge.cancellation import ingestion_task,check_cancelled
from app.knowledge.generations import generation_store,StaleGeneration
user,kb,doc,generation,directory=sys.argv[1:]
root=Path(directory)
source=root/'old.txt'
source.write_text('Obsolete generation evidence must never replace the latest version.')
original=generation_store.writing
@contextmanager
def pause(*args,**kwargs):
 check_cancelled()
 (root/'ready').write_text('lease checkpoint passed')
 deadline=time.monotonic()+180
 while not (root/'release').exists():
  if time.monotonic()>deadline: raise TimeoutError('QA pause timed out')
  time.sleep(.05)
 with original(*args,**kwargs): yield
generation_store.writing=pause
result={}
try:
 with ingestion_task(user,'generation-qa-'+uuid.uuid4().hex):
  ingestion.ingest_document(user,kb,str(source),'generation.txt',doc,report={},index_generation=int(generation))
 result={'result':'unexpected_write'}
except StaleGeneration:
 result={'result':'fenced'}
except Exception as error:
 result={'result':'error','type':type(error).__name__}
finally:
 (root/'outcome.json').write_text(json.dumps(result))
 source.unlink(missing_ok=True)
`
    folder = python(`import subprocess,tempfile,json,sys\nfrom pathlib import Path\nroot=Path(tempfile.mkdtemp(prefix='mneme-generation-qa-'))\nwith (root/'worker.log').open('w') as log:\n child=subprocess.Popen([sys.executable,'-c',${JSON.stringify(worker)},*sys.argv[1:],str(root)],stdout=log,stderr=log,start_new_session=True)\n(root/'pid').write_text(str(child.pid))\nprint(str(root))`, user, kb.id, `doc_${doc.id}`, firstGeneration + 1)
    expect(folder).toMatch(/^\/tmp\/mneme-generation-qa-/)
    await expect.poll(() => python("from pathlib import Path\nimport sys\nprint((Path(sys.argv[1])/'ready').exists())", folder), { timeout: 30000 }).toBe('True')
    await api('post', `/knowledge/document/${doc.id}/replace`, { multipart: {
      file: { name: 'generation.txt', mimeType: 'text/plain', buffer: Buffer.from('Latest generation evidence: durable fencing protects the current published document.') },
    } })
    // The first replacement attempt reuses the abandoned reservation and must
    // fail closed. The durable Gateway retry allocates a strictly newer one.
    await expect.poll(async () => {
      const current = await status()
      return current.status === 'ready' && JSON.parse(current.parseReport).index_generation > firstGeneration + 1
    }, { timeout: 90000, intervals: [500, 1000, 2000] }).toBe(true)
    const current = await status()
    const latestGeneration = JSON.parse(current.parseReport).index_generation
    expect(Number(current.indexGeneration)).toBe(latestGeneration)
    expect(current.errorMessage).toBeNull()
    const snapshot = () => JSON.parse(python(`import json,hashlib,sys
from app.knowledge.vector_store import vector_store
from app.knowledge.lexical_index import lexical_index
from app.knowledge.generations import generation_store
user,kb,doc=sys.argv[1:]
c=vector_store.get_collection(user,kb)
rows=c.get(where={'document_id':doc},include=['documents','metadatas','embeddings'])
print(json.dumps({'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest(),'generations':sorted(set(m['index_generation'] for m in rows['metadatas'])),'fts':lexical_index.document_version(user,kb,doc),'active':generation_store.snapshot(user)['libraries'][kb]['documents'][doc]['active']}))`, user, kb.id, `doc_${doc.id}`))
    const before = snapshot()
    expect(before.generations).toEqual([latestGeneration])
    expect(before.active).toBe(latestGeneration)
    python("from pathlib import Path\nimport sys\n(Path(sys.argv[1])/'release').touch()", folder)
    await expect.poll(() => python("from pathlib import Path\nimport sys\np=Path(sys.argv[1])/'outcome.json'\nprint(p.read_text() if p.exists() else '{}')", folder), { timeout: 30000 }).toBe('{"result": "fenced"}')
    expect(snapshot()).toEqual(before)
    const chunks = (await api('get', `/workspace/retrieval/debug?kbId=${kb.id}&query=generation%20evidence&documentIds=${doc.id}`)).chunks
    expect(chunks.length).toBeGreaterThan(0)
    expect(chunks.every(chunk => chunk.metadata.index_generation === latestGeneration)).toBeTruthy()
    expect(chunks.map(chunk => chunk.content).join('\n')).toContain('Latest generation evidence')
    expect(chunks.map(chunk => chunk.content).join('\n')).not.toMatch(/Obsolete|Original/)
    await page.goto('/knowledge')
    await page.getByRole('button', { name: 'generation.txt', exact: true }).click()
    await expect(page.locator('.document-paper pre')).toContainText('Latest generation evidence')
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBeFalsy()
    await page.screenshot({ path: testInfo.outputPath('latest-generation.png'), fullPage: true })
    await testInfo.attach('generation-evidence', { body: Buffer.from(JSON.stringify({ firstGeneration, latestGeneration, oldWorker: 'fenced', unchangedAfterResume: true, snapshot: before }, null, 2)), contentType: 'application/json' })
  } finally {
    if (folder) python(`import os,sys,signal,shutil,time\nfrom pathlib import Path\np=Path(sys.argv[1]).resolve()\nassert p.parent==Path('/tmp') and p.name.startswith('mneme-generation-qa-')\n(p/'release').touch()\nif not (p/'outcome.json').exists():\n try: os.kill(int((p/'pid').read_text()),signal.SIGTERM)\n except ProcessLookupError: pass\n time.sleep(.2)\nshutil.rmtree(p)`, folder)
    await api('delete', '/profile/account')
  }
})
