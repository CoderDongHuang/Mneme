import { afterEach, expect, test } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { setLanguage, t, useI18n } from './index'

afterEach(async () => { await act(() => setLanguage('zh-CN')) })
function Example() {
  useI18n()
  return <><h1>{t('学习记忆')}</h1><p>{t('删除反馈 {0}', ['用户的中文标题'])}</p><article>用户的中文原文</article></>
}
test('switches mounted UI while preserving user content and interpolation values', async () => {
  render(<Example />)
  expect(screen.getByRole('heading')).toHaveTextContent('学习记忆')
  await act(() => setLanguage('en'))
  expect(screen.getByRole('heading')).toHaveTextContent('Learning memory')
  expect(screen.getByText('用户的中文原文')).toBeVisible()
  expect(screen.getByText(/用户的中文标题/)).toHaveTextContent('用户的中文标题')
})
test('a stale asynchronous English load cannot override the latest Chinese choice', async () => {
  const pending = setLanguage('en')
  await setLanguage('zh-CN')
  await pending
  expect(t('登录')).toBe('登录')
})
