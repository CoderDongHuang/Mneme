import contract from '../../../contracts/chat-stream.schema.json'

// The supported JSON Schema vocabulary is deliberately bounded and checked in
// tests. Unsupported future constraints fail closed rather than silently drift.
const vocabulary = new Set(['$ref', 'title', 'description', 'default', 'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'const', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'])

function matches(schema, value) {
  if (Object.keys(schema).some(key => !vocabulary.has(key))) return false
  if (schema.$ref) return matches(contract.$defs[schema.$ref.split('/').pop()], value)
  if (schema.anyOf && !schema.anyOf.some(choice => matches(choice, value))) return false
  if ('const' in schema && value !== schema.const) return false
  if (schema.enum && !schema.enum.includes(value)) return false
  const object = value !== null && typeof value === 'object' && !Array.isArray(value)
  const types = { object, array: Array.isArray(value), string: typeof value === 'string', boolean: typeof value === 'boolean', number: typeof value === 'number' && Number.isFinite(value), integer: typeof value === 'number' && Number.isInteger(value), null: value === null }
  if (schema.type && !types[schema.type]) return false
  if (typeof value === 'number' && ((schema.minimum !== undefined && value < schema.minimum) || (schema.maximum !== undefined && value > schema.maximum))) return false
  if (typeof value === 'string') {
    const length = Array.from(value).length
    if ((schema.minLength !== undefined && length < schema.minLength) || (schema.maxLength !== undefined && length > schema.maxLength)) return false
  }
  if (Array.isArray(value) && schema.items && !value.every(item => matches(schema.items, item))) return false
  if (object) {
    if (schema.required?.some(key => !Object.hasOwn(value, key))) return false
    for (const [key, item] of Object.entries(value)) {
      const field = schema.properties && Object.hasOwn(schema.properties, key) ? schema.properties[key] : undefined
      if (field ? !matches(field, item) : schema.additionalProperties === false || (typeof schema.additionalProperties === 'object' && !matches(schema.additionalProperties, item))) return false
    }
  }
  return true
}

/** @param {keyof import('./generated/chat-stream').ChatStreamPayloads} event */
export function validChatEvent(event, payload) {
  return Object.hasOwn(contract.events, event) && matches(contract.events[event], payload)
}
