import { expect, test } from 'vitest'
import { checkBudget } from '../../scripts/bundle-budget'

const manifest = {
  entry: { isEntry: true, file: 'index.js', imports: ['shared'], css: ['style.css'], dynamicImports: ['page'] },
  shared: { file: 'shared.js', imports: ['entry'], css: ['style.css'] },
  page: { isDynamicEntry: true, file: 'page.js' },
}
test('budget includes all static dependencies once and excludes lazy routes', () => {
  const loaded = []
  const result = checkBudget(manifest, file => { loaded.push(file); return 'small bundle' })
  expect(result.files).toEqual(['index.js', 'style.css', 'shared.js'])
  expect(loaded).toEqual(result.files)
})
test('oversized dependencies and incomplete manifests fail the build', () => {
  expect(() => checkBudget(manifest, () => 'large', { js: 1, css: 1 })).toThrow('budget exceeded')
  expect(() => checkBudget({ entry: manifest.entry }, () => '')).toThrow('Missing manifest import')
  expect(() => checkBudget({}, () => '')).toThrow('No bundle entry')
})
test('first-screen budget includes the active route as well as its static dependencies', () => {
  const result = checkBudget(manifest, () => 'bundle', { js: 1024, css: 1024 }, ['page'])
  expect(result.files).toContain('page.js')
  expect(() => checkBudget(manifest, () => 'bundle', { js: result.js - 1, css: 1024 }, ['page'])).toThrow('budget exceeded')
})
