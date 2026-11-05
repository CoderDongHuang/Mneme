import { parseInstant } from '../../utils/dates'

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const id = value => Number.isSafeInteger(value) && value > 0
const text = value => typeof value === 'string'
const date = value => {
  if (!text(value) || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
const instant = value => text(value) && date(value.slice(0, 10))
  && /^\d{4}-\d{2}-\d{2}[T ](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(value) && !!parseInstant(value)
const collection = (value, valid) => Array.isArray(value) && value.every(valid)
  && new Set(value.map(item => item.id)).size === value.length

export const validReview = value => record(value) && id(value.id)
  && text(value.prompt) && text(value.answer) && instant(value.due_at)
  && Number.isSafeInteger(value.review_count) && value.review_count >= 0
  && (value.origin == null || text(value.origin))
export const validPlan = value => record(value) && id(value.id)
  && text(value.title) && !!value.title.trim() && text(value.goal)
  && (value.target_date == null || date(value.target_date))
export const validReviews = value => collection(value, validReview)
export const validPlans = value => collection(value, validPlan)
export const validRatingReceipt = (value, card, rating) => validReview(value)
  && value.id === card.id && value.review_count > card.review_count
  && (value.last_rating == null || value.last_rating === rating)
