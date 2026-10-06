import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { checkBudget } from './bundle-budget.js'

const dist = new URL('../dist/', import.meta.url)
const manifest = JSON.parse(readFileSync(new URL('.vite/manifest.json', dist), 'utf8'))
const pages = Object.entries(manifest).filter(([key]) => key.startsWith('src/pages/'))
if (pages.length !== 13 || pages.some(([, chunk]) => !chunk.isDynamicEntry)) {
  throw new Error('All 13 route pages must be lazy dynamic entries')
}
const result = checkBudget(manifest, file => readFileSync(fileURLToPath(new URL(file, dist))))
console.log(`Initial gzip: JS ${(result.js / 1024).toFixed(2)} KiB / 120 KiB; CSS ${(result.css / 1024).toFixed(2)} KiB / 24 KiB. 13 lazy routes.`)
for (const [key] of pages) {
  const route = checkBudget(manifest, file => readFileSync(fileURLToPath(new URL(file, dist))),
    { js: 140 * 1024, css: 16 * 1024 }, [key])
  console.log(`${key}: entry + route gzip JS ${(route.js / 1024).toFixed(2)} KiB / 140 KiB; CSS ${(route.css / 1024).toFixed(2)} KiB / 16 KiB`)
}
