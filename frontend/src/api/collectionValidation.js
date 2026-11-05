const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const id = value => Number.isSafeInteger(value) && value > 0
const text = value => typeof value === 'string'
const optionalText = value => value == null || text(value)
const unique = (items, key) => new Set(items.map(item => item?.[key])).size === items.length
export const validBases = value => Array.isArray(value) && unique(value, 'id') && value.every(item => record(item)
  && id(item.id) && text(item.name) && item.name.trim() && optionalText(item.description))
export const validSessions = value => Array.isArray(value) && unique(value, 'id') && value.every(item => record(item) && id(item.id) && ['title', 'createdAt', 'updatedAt'].every(key => optionalText(item[key])))
