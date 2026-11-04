import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import DocumentIndexHealth from './DocumentIndexHealth'

const document = (status, lexical = null) => ({ id: 7, status, parseReport: JSON.stringify({ vector_index_version: 'a'.repeat(64), lexical_index_version: lexical, index_status: lexical ? 'ready' : 'pending' }) })

test('partial index explains retained vectors and submits only lexical repair', () => {
  const repair = vi.fn(), doc = document('index_pending')
  render(<DocumentIndexHealth document={doc} onRepair={repair} />)
  expect(screen.getByRole('status')).toHaveTextContent('向量索引可用，词法索引待修复')
  fireEvent.click(screen.getByRole('button', { name: '修复词法索引' }))
  expect(repair).toHaveBeenCalledWith(doc)
})

test('accepted task stays pending and cannot be double-submitted; ready requires matching versions', () => {
  const repair = vi.fn()
  const { rerender } = render(<DocumentIndexHealth document={document('index_repairing')} onRepair={repair} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByRole('link')).toHaveAttribute('href', '/tasks')
  rerender(<DocumentIndexHealth document={document('ready', 'b'.repeat(64))} onRepair={repair} />)
  expect(screen.getByRole('status')).toHaveTextContent('词法索引待修复')
  rerender(<DocumentIndexHealth document={document('ready', 'a'.repeat(64))} onRepair={repair} />)
  expect(screen.getByRole('status')).toHaveTextContent('向量与词法索引版本一致')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test.each(['null', '[]', '{"vector_index_version":7}', '{"vector_index_version":"abc","lexical_index_version":{}}', '{"vector_index_version":"abc","index_status":[]}'])('invalid report %s cannot crash or offer repair', parseReport => {
  const repair = vi.fn()
  render(<DocumentIndexHealth document={{ id: 7, status: 'ready', parseReport }} onRepair={repair} />)
  expect(screen.getByRole('alert')).toHaveTextContent('解析报告格式无效，请重新解析')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(repair).not.toHaveBeenCalled()
})
