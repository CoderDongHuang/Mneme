import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CleanupChecklist from './CleanupChecklist'

describe('deletion readback checklist', () => {
  it('distinguishes unreadable stores from zero and shows residual counts', () => {
    render(<CleanupChecklist report={JSON.stringify({ status: 'pending', counts: { qdrant_chunks: 0, fts_rows: -1, files: 2 } })} />)
    expect(screen.getByText('清理待核验')).toBeInTheDocument()
    expect(screen.getByText('未知（读取失败）')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })
  it('does not report legacy or malformed receipts as verified', () => {
    const { rerender } = render(<CleanupChecklist />)
    expect(screen.getByText('尚未核验')).toBeInTheDocument()
    rerender(<CleanupChecklist report="broken" />)
    expect(screen.getByText('核验清单不可用')).toBeInTheDocument()
  })
  it('requires zero counts even when a receipt claims verification', () => {
    const { rerender } = render(<CleanupChecklist report={{ status: 'verified', counts: { fts_rows: -1 } }} />)
    expect(screen.getByText('清理待核验')).toBeInTheDocument()
    rerender(<CleanupChecklist report={{ status: 'verified', counts: {} }} />)
    expect(screen.getByText('清理待核验')).toBeInTheDocument()
    rerender(<CleanupChecklist report={{ status: 'verified', counts: { fts_rows: 0, files: 0 } }} />)
    expect(screen.getByText('清理已核验')).toBeInTheDocument()
  })
})
