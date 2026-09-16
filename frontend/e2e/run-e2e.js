import { spawn } from 'node:child_process'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'
import process from 'node:process'

const baseUrl = 'http://127.0.0.1:4173'
const dist = normalize(join(process.cwd(), 'dist'))
const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
}
const server = createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, baseUrl).pathname)
  const requested = normalize(join(dist, pathname.replace(/^\/+/, '')))
  const file = requested.startsWith(dist) && existsSync(requested) && statSync(requested).isFile()
    ? requested
    : join(dist, 'index.html')
  response.setHeader('Content-Type', mimeTypes[extname(file)] || 'application/octet-stream')
  createReadStream(file).pipe(response)
})

let exitCode
try {
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(4173, '127.0.0.1', resolve)
  })
  const runner = spawn(
    process.execPath,
    ['./node_modules/@playwright/test/cli.js', 'test', ...process.argv.slice(2)],
    {
      stdio: 'inherit',
      env: { ...process.env, MNEME_E2E_BASE_URL: baseUrl },
    },
  )
  exitCode = await new Promise((resolve) => runner.once('exit', (code) => resolve(code ?? 1)))
} finally {
  await new Promise((resolve) => server.close(resolve))
}

process.exitCode = exitCode ?? 1
