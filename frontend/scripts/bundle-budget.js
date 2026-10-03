import { gzipSync } from 'node:zlib'

export function checkBudget(manifest, load, limits = { js: 120 * 1024, css: 24 * 1024 }, activeRoutes = []) {
  const visited = new Set()
  const files = new Set()
  function visit(key) {
    if (visited.has(key)) return
    const chunk = manifest[key]
    if (!chunk) throw new Error(`Missing manifest import: ${key}`)
    visited.add(key)
    files.add(chunk.file)
    for (const css of chunk.css || []) files.add(css)
    for (const dependency of chunk.imports || []) visit(dependency)
  }
  const entries = Object.entries(manifest).filter(([, value]) => value.isEntry)
  if (!entries.length) throw new Error('No bundle entry found')
  for (const [key] of entries) visit(key)
  for (const key of activeRoutes) visit(key)
  const result = { js: 0, css: 0, files: [...files] }
  for (const file of files) {
    const type = file.endsWith('.js') ? 'js' : file.endsWith('.css') ? 'css' : null
    if (type) result[type] += gzipSync(load(file)).length
  }
  for (const type of ['js', 'css']) {
    if (result[type] > limits[type]) throw new Error(`Initial ${type} gzip budget exceeded: ${result[type]} > ${limits[type]} bytes`)
  }
  return result
}
