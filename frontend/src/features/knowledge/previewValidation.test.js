import { expect, test } from 'vitest'
import { validDocumentPreview } from './previewValidation'

const preview = () => ({
  document: { id: 7, file_name: 'scan.pdf', sha256: 'a'.repeat(64), chunk_count: 1, version_number: 2 },
  content: 'OCR content', extension: 'pdf', parse_report: {
    page_count: 1, chunk_count: 1, preview_truncated: false, chunks_truncated: false,
    pages: [{ page: 1, text: 'OCR content', ocr_confidence_min: 0,
      blocks: [{ type: 'text', section: '', content: 'OCR content' }],
      ocr_regions: [{ text: 'OCR', confidence: .7, region: '0,0,1,1' }] }],
    chunks: [{ index: 0, page: 1, type: 'text', content: 'OCR content' }],
  },
})

test('retains valid OCR, zero values, truncation and historical reports without coercion', () => {
  const value = preview()
  expect(validDocumentPreview(value, '7', 'a'.repeat(64))).toBe(true)
  expect(value.parse_report.pages[0].ocr_confidence_min).toBe(0)
  expect(validDocumentPreview({ ...value, parse_report: { pages: [], status: 'historical_report_unavailable' } })).toBe(true)
  expect(validDocumentPreview({ ...value, parse_report: { pages: [], status: 'unavailable' } })).toBe(true)
})

test.each([
  ['page list object', p => { p.parse_report.pages = {} }],
  ['duplicate pages', p => { p.parse_report.pages.push(p.parse_report.pages[0]) }],
  ['non numeric page', p => { p.parse_report.pages[0].page = '1' }],
  ['blocks object', p => { p.parse_report.pages[0].blocks = {} }],
  ['block content object', p => { p.parse_report.pages[0].blocks[0].content = {} }],
  ['OCR list object', p => { p.parse_report.pages[0].ocr_regions = {} }],
  ['OCR region object', p => { p.parse_report.pages[0].ocr_regions[0].region = {} }],
  ['OCR missing coordinate', p => { p.parse_report.pages[0].ocr_regions[0].region = '0,,1,1' }],
  ['OCR out of bounds', p => { p.parse_report.pages[0].ocr_regions[0].region = '0,0,2,1' }],
  ['OCR inverted', p => { p.parse_report.pages[0].ocr_regions[0].region = '1,0,0,1' }],
  ['OCR non finite', p => { p.parse_report.pages[0].ocr_regions[0].confidence = Infinity }],
  ['OCR wrong confidence', p => { p.parse_report.pages[0].ocr_confidence_min = [] }],
  ['chunks object', p => { p.parse_report.chunks = {} }],
  ['chunk null', p => { p.parse_report.chunks = [null] }],
  ['chunk object text', p => { p.parse_report.chunks[0].content = {} }],
  ['wrong count', p => { p.parse_report.page_count = '1' }],
  ['wrong flag', p => { p.parse_report.preview_truncated = 'false' }],
  ['wrong content', p => { p.content = {} }],
  ['wrong extension', p => { p.extension = [] }],
  ['invalid hash', p => { p.document.sha256 = '../other' }],
])('rejects %s before consumers render or navigate', (_, change) => {
  const value = preview(); change(value)
  expect(validDocumentPreview(value, 7)).toBe(false)
})

test('requested document and historical hash must match the response', () => {
  expect(validDocumentPreview(preview(), 8)).toBe(false)
  expect(validDocumentPreview(preview(), 7, 'b'.repeat(64))).toBe(false)
})
