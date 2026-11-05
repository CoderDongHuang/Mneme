const record = value => !!value && typeof value === 'object' && !Array.isArray(value)
const optional = (value, key, valid) => value[key] === undefined || valid(value[key])
const boolean = value => typeof value === 'boolean'
const latency = value => Number.isSafeInteger(value) && value >= 0
const modelName = value => typeof value === 'string' && /^[A-Za-z0-9._:/-]{1,120}$/.test(value)
const states = new Set(['ok', 'disabled', 'missing_credentials', 'model_not_loaded', 'timeout', 'authentication_failed', 'quota_or_rate_limit', 'model_unsupported', 'runtime_missing', 'provider_or_network_error'])

export function validModelSettings(value) {
  return record(value) && ['deepseek', 'dashscope', 'openai'].includes(value.provider)
    && modelName(value.model) && boolean(value.enabled) && !Object.hasOwn(value, 'apiKey')
    && optional(value, 'hasKey', boolean)
    && optional(value, 'keyMask', mask => typeof mask === 'string' && mask.length <= 32)
    && optional(value, 'baseUrl', url => typeof url === 'string')
}

export function validPersonalProbe(value) {
  return record(value) && modelName(value.model) && latency(value.latency_ms)
    && optional(value, 'status', status => status === 'ok')
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
