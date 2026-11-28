import modelContract from '../../../../contracts/settings-model.schema.json'
import { matchesSchema } from '../../api/schemaContract'

const record = value => !!value && typeof value === 'object' && !Array.isArray(value)
const optional = (value, key, valid) => value[key] === undefined || valid(value[key])
const boolean = value => typeof value === 'boolean'
const latency = value => Number.isSafeInteger(value) && value >= 0
const modelName = value => typeof value === 'string' && /^[A-Za-z0-9._:/-]{1,120}$/.test(value)
// Java String.trim removes code units through U+0020.
// eslint-disable-next-line no-control-regex
export const javaTrim = value => value.replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '')
const definitions = modelContract.$defs
const states = new Set(['ok', 'disabled', 'missing_credentials', 'model_not_loaded', 'timeout', 'authentication_failed', 'quota_or_rate_limit', 'model_unsupported', 'runtime_missing', 'provider_or_network_error'])

export function validModelSettings(value) {
  return matchesSchema(definitions.ModelSettings, value, definitions) && modelName(value.model) && !Object.hasOwn(value, 'apiKey')
}

export function validModelSettingsUpdate(value) {
  if (!matchesSchema(definitions.ModelSettingsUpdateRequest, value, definitions)) return false
  if (value.model !== undefined && !modelName(javaTrim(value.model))) return false
  const apiKey = value.clearKey ? '' : javaTrim(value.apiKey ?? '')
  if (apiKey.length > 512 || [...apiKey].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return false
  return true
}

export function validPersonalProbe(value) {
  return matchesSchema(definitions.ModelTestReceipt, value, definitions) && modelName(value.model) && latency(value.latency_ms)
}

export function validProviders(value) {
  return record(value) && record(value.results)
    && ['chat', 'embedding', 'rerank', 'ocr'].every(name => {
      const result = value.results[name]
      return record(result) && states.has(result.state) && latency(result.latency_ms)
    }) && optional(value, 'cached', boolean) && optional(value, 'cache_seconds', latency)
}

export function validHealth(value) {
  if (!record(value) || !(value.status === 'unavailable' || value.service === 'mneme-python-agent')) return false
  if (!optional(value, 'demo_mode', boolean) || !optional(value, 'status', status => ['ok', 'unavailable'].includes(status))) return false
  if (value.storage === undefined) return true
  return record(value.storage) && optional(value.storage, 'backend', backend => ['local', 's3'].includes(backend))
    && ['object_storage_ready', 'file_root_exists', 'tenant_scoped_paths', 'traversal_guard', 'archive_import_guard'].every(key => optional(value.storage, key, boolean))
}
