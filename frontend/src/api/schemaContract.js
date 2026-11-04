// The supported JSON Schema vocabulary is deliberately bounded and checked in
// tests. Unsupported future constraints fail closed rather than silently drift.
const vocabulary = new Set(['$ref', 'title', 'description', 'default', 'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'const', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'])

export function matchesSchema(schema, value, definitions = {}) {
  if (!schema || typeof schema !== 'object') return false
  if (Object.keys(schema).some(key => !vocabulary.has(key))) return false
  if (schema.$ref) return matchesSchema(definitions[schema.$ref.split('/').pop()], value, definitions)
  if (schema.anyOf && !schema.anyOf.some(choice => matchesSchema(choice, value, definitions))) return false
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
  if (Array.isArray(value) && schema.items && !value.every(item => matchesSchema(schema.items, item, definitions))) return false
  if (object) {
    if (schema.required?.some(key => !Object.hasOwn(value, key))) return false
    for (const [key, item] of Object.entries(value)) {
      const field = schema.properties && Object.hasOwn(schema.properties, key) ? schema.properties[key] : undefined
      if (field ? !matchesSchema(field, item, definitions) : schema.additionalProperties === false || (typeof schema.additionalProperties === 'object' && !matchesSchema(schema.additionalProperties, item, definitions))) return false
    }
  }
  return true
}

