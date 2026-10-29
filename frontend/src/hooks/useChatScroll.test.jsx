import { act, fireEvent, renderHook } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import useChatScroll from './useChatScroll'

test('streaming follows only near bottom and the reader can explicitly return', () => {
  const node = document.createElement('div')
  Object.defineProperties(node, { scrollHeight: { value: 1000 }, clientHeight: { value: 300 } })
  node.scrollTop = 700
  const ref = { current: node }
  const frames = []
  vi.stubGlobal('requestAnimationFrame', callback => { frames.push(callback); return frames.length })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const { result, rerender } = renderHook(({ messages }) => useChatScroll(ref, messages), { initialProps: { messages: [] } })
  act(() => frames.splice(0).forEach(callback => callback()))
  node.scrollTop = 100
  fireEvent.scroll(node)
  rerender({ messages: [{ content: 'new token' }] })
  act(() => frames.splice(0).forEach(callback => callback()))
  expect(node.scrollTop).toBe(100)
  expect(result.current.unseen).toBe(true)
  act(() => result.current.scrollToBottom())
  expect(node.scrollTop).toBe(1000)
  expect(result.current.unseen).toBe(false)
  vi.unstubAllGlobals()
})
