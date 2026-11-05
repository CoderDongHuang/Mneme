// Validate only the fields used by preview consumers. Unknown parser metadata
// stays intact so older reports and future parser versions remain readable.
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const integer = value => Number.isSafeInteger(value) && value >= 0
const positive = value => integer(value) && value > 0
const text = value => typeof value === 'string'
const optional = (value, check) => value == null || check(value)
const list = (value, check) => value === undefined || (Array.isArray(value) && value.every(check))
const confidence = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
const hash = value => text(value) && /^[a-fA-F0-9]{64}$/.test(value)
const identifier = value => (typeof value === 'number' && positive(value)) || (text(value) && /^[1-9]\d*$/.test(value))

function region(value) {
  if (!text(value)) return false
  const parts = value.split(',')
  if (parts.length !== 4 || parts.some(part => !part.trim())) return false
  const [left, top, right, bottom] = parts.map(Number)
  return [left, top, right, bottom].every(confidence) && left <= right && top <= bottom
}

export function validIndexReport(report) {
  return record(report) && ['vector_index_version', 'lexical_index_version', 'index_status']
    .every(key => optional(report[key], text))
}

function validPage(page) {
  return record(page) && positive(page.page) && optional(page.text, text)
    && ['ocr_confidence_min', 'ocr_confidence_avg'].every(key => optional(page[key], confidence))
    && list(page.blocks, block => record(block) && text(block.content)
      && optional(block.type, text) && optional(block.section, text))
    && list(page.ocr_regions, item => record(item) && text(item.text) && confidence(item.confidence) && region(item.region))
}

export function validDocumentPreview(value, expectedId, expectedSha) {
  if (!record(value) || !record(value.document) || !identifier(value.document.id)
    || (expectedId != null && String(value.document.id) !== String(expectedId))
    || !text(value.extension) || !text(value.content) || !validIndexReport(value.parse_report)) return false
  const doc = value.document, report = value.parse_report
  if (!optional(doc.file_name, text) || !optional(doc.chunk_count, integer)
    || !optional(doc.sha256, hash) || !optional(doc.version_number, positive)
    || (expectedSha && doc.sha256?.toLowerCase() !== expectedSha.toLowerCase())) return false
  if (!['page_count', 'chunk_count'].every(key => optional(report[key], integer))
    || !['preview_truncated', 'chunks_truncated'].every(key => optional(report[key], flag => typeof flag === 'boolean'))
    || !optional(report.status, text) || !optional(report.content_sha256, hash)
    || !list(report.pages, validPage)
    || !list(report.chunks, chunk => record(chunk) && text(chunk.content)
      && optional(chunk.page, integer) && optional(chunk.index, integer) && optional(chunk.type, text))) return false
  const pages = report.pages || []
  return new Set(pages.map(page => page.page)).size === pages.length
}
