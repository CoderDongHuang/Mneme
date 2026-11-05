import { parseInstant } from '../../utils/dates'

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const text = value => typeof value === 'string'
const id = value => Number.isSafeInteger(value) && value > 0
const score = value => Number.isInteger(value) && value >= 0 && value <= 100
const unique = items => new Set(items.map(item => item.id)).size === items.length
export function quizArray(value) {
  try { const parsed = text(value) ? JSON.parse(value) : value; return Array.isArray(parsed) ? parsed : null } catch { return null }
}
const option = value => text(value) || (record(value) && text(value.text ?? value.label)
  && [value.value, value.key].every(key => key == null || text(key) || Number.isFinite(key)))
const question = value => record(value) && ['short', 'choice'].includes(value.type)
  && text(value.prompt) && !!value.prompt.trim() && (value.hint == null || text(value.hint))
  && (value.options == null ? value.type === 'short' : Array.isArray(value.options)
    && value.options.every(option) && (value.type !== 'choice' || value.options.length >= 2))
export const validQuiz = value => record(value) && id(value.id) && text(value.title) && !!value.title.trim()
  && quizArray(value.questions_json) !== null && quizArray(value.questions_json).every(question)
export const validQuizzes = value => Array.isArray(value) && value.every(validQuiz) && unique(value)
const answers = (value, count) => {
  const items = quizArray(value)
  return items !== null && items.length <= count && items.every(item => text(item) && item.length <= 10000)
}
export const validDraft = (value, count) => record(value) && answers(value.answers_json, count)
  && Number.isInteger(value.current_question) && value.current_question >= 0 && value.current_question < Math.max(1, count)
export const validDraftReceipt = (value, draft, count) => validDraft(value, count)
  && value.current_question === draft.current_question
  && JSON.stringify(quizArray(value.answers_json)) === JSON.stringify(draft.answers)
const source = value => value == null || (record(value)
  && (value.document_id == null || id(value.document_id) || (text(value.document_id) && /^(?:doc_)?[1-9]\d*$/.test(value.document_id)))
  && (value.page == null || id(value.page)))
const feedback = (value, count) => {
  const items = quizArray(value)
  return items !== null && items.length <= count && items.every((item, index) => record(item)
    && (item.question_id == null || item.question_id === index + 1)
    && typeof item.correct === 'boolean' && text(item.expected) && text(item.evidence) && source(item.source))
}
export const validAttempts = (value, count) => Array.isArray(value) && value.every(item => record(item)
  && id(item.id) && score(item.score) && (item.raw_score == null || score(item.raw_score))
  && answers(item.answers_json, count) && feedback(item.feedback_json, count)
  && text(item.created_at) && !!parseInstant(item.created_at)) && unique(value)
export const validSubmission = (value, count) => record(value) && score(value.score)
  && (value.raw_score == null || score(value.raw_score)) && feedback(value.feedback, count)
  && value.feedback.length === count
