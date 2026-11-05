const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const text = value => typeof value === 'string'
const optionalText = value => value == null || text(value)
const identifier = value => text(value) && value.trim().length > 0
const confidence = value => value == null || (Number.isFinite(value) && value >= 0 && value <= 1)
const unique = (items, key) => new Set(items.map(item => item?.[key])).size === items.length

export function memoryTags(value) {
  try {
    const tags = value == null ? [] : text(value) ? JSON.parse(value) : value
    return Array.isArray(tags) && tags.every(text) ? tags : null
  } catch { return null }
}

export const validMemory = item => record(item) && identifier(item.id) && text(item.content)
  && ['category', 'topic', 'status', 'updated_at'].every(key => optionalText(item[key]))
  && (item.confirmed == null || typeof item.confirmed === 'boolean' || item.confirmed === 0 || item.confirmed === 1)
  && (item.source_session_id == null || text(item.source_session_id) || (Number.isSafeInteger(item.source_session_id) && item.source_session_id > 0))
  && confidence(item.confidence) && memoryTags(item.tags) !== null

export const validManagedMemories = value => record(value) && Array.isArray(value.memories)
  && unique(value.memories, 'id') && value.memories.every(validMemory)

export const validPendingMemories = value => Array.isArray(value) && unique(value, 'memoryId')
  && value.every(item => record(item) && identifier(item.memoryId) && text(item.content)
    && ['category', 'topic'].every(key => optionalText(item[key])) && confidence(item.confidence)
    && (item.sessionId == null || text(item.sessionId) || (Number.isSafeInteger(item.sessionId) && item.sessionId > 0)))

export const validMemoryVersions = value => record(value) && Array.isArray(value.versions)
  && unique(value.versions, 'version') && value.versions.every(item => record(item)
    && Number.isSafeInteger(item.version) && item.version > 0 && text(item.content)
    && ['reason', 'action'].every(key => optionalText(item[key])))
