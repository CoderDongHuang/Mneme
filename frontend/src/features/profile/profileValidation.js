const record = value => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value, max) => value === null || typeof value === 'string' && value.length <= max

export function validProfile(value, owner = {}) {
  return record(value) && typeof value.username === 'string' && !!value.username.trim() && value.username.length <= 50
    && text(value.nickname, 50) && text(value.email, 120) && typeof value.emailVerified === 'boolean'
    && (value.hasAvatar === undefined || typeof value.hasAvatar === 'boolean')
    && (value.role === undefined || ['user', 'admin'].includes(value.role))
    && (value.userId === undefined || (typeof value.userId === 'string' && /^\d{1,20}$/.test(value.userId) || Number.isSafeInteger(value.userId) && value.userId > 0))
    && (!owner.username || value.username === owner.username)
    && (!owner.userId || value.userId === undefined || String(value.userId) === String(owner.userId))
}

export function validEmailReceipt(value) {
  return record(value) && Number.isSafeInteger(value.expiresInSeconds) && value.expiresInSeconds > 0
    && (value.resendAfterSeconds === undefined || Number.isSafeInteger(value.resendAfterSeconds) && value.resendAfterSeconds > 0)
}
