import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom has no layout engine. Keep the shared responsive-detail component on
// its desktop branch; browser tests exercise the real mobile media query.
Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(query => ({
  matches: false, media: query, onchange: null,
  addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true },
})) })

afterEach(() => cleanup())
