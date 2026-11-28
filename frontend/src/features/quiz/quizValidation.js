import contract from '../../../../contracts/quiz.schema.json'
import { matchesSchema } from '../../api/schemaContract'
import { parseInstant } from '../../utils/dates'

const definitions = contract.$defs

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const text = value => typeof value === 'string'
const id = value => Number.isSafeInteger(value) && value > 0
const score = value => Number.isInteger(value) && value >= 0 && value <= 100
const unique = items => new Set(items.map(item => item.id)).size === items.length
export function quizArray(value) {
  try { const parsed = text(value) ? JSON.parse(value) : value; return Array.isArray(parsed) ? parsed : null } catch { return null }
}
const question = value => matchesSchema(definitions.QuizQuestion, value, definitions)
  && !!value.prompt.trim() && (value.options == null ? value.type === 'short' : value.type !== 'choice' || value.options.length >= 2)
export const validQuiz = value => matchesSchema(definitions.Quiz, value, definitions) && id(value.id) && !!value.title.trim()
  && quizArray(value.questions_json) !== null && quizArray(value.questions_json).every(question)
export const validQuizzes = value => Array.isArray(value) && value.every(validQuiz) && unique(value)
const answers = (value, count) => {
  const items = quizArray(value)
  return items !== null && items.length <= count && items.every(item => text(item) && item.length <= 10000)
}
export const validDraft = (value, count) => matchesSchema(definitions.QuizDraft, value, definitions) && answers(value.answers_json, count)
  && Number.isInteger(value.current_question) && value.current_question >= 0 && value.current_question < Math.max(1, count)
export const validDraftReceipt = (value, draft, count) => validDraft(value, count)
  && value.current_question === draft.current_question
  && JSON.stringify(quizArray(value.answers_json)) === JSON.stringify(draft.answers)
const source = value => value == null || (record(value)
  && (value.document_id == null || id(value.document_id) || (text(value.document_id) && /^(?:doc_)?[1-9]\d*$/.test(value.document_id)))
  && (value.page == null || id(value.page)))
const feedback = (value, count) => {
  const items = quizArray(value)
  return items !== null && items.length <= count && items.every((item, index) => matchesSchema(definitions.QuizFeedback, item, definitions)
    && (item.question_id == null || item.question_id === index + 1)
    && typeof item.correct === 'boolean' && text(item.expected) && text(item.evidence) && source(item.source))
}
export const validAttempts = (value, count) => Array.isArray(value) && value.every(item => matchesSchema(definitions.QuizAttempt, item, definitions)
  && id(item.id) && score(item.score) && (item.raw_score == null || score(item.raw_score))
  && answers(item.answers_json, count) && feedback(item.feedback_json, count)
  && text(item.created_at) && !!parseInstant(item.created_at)) && unique(value)
export const validSubmission = (value, count) => matchesSchema(definitions.QuizSubmissionReceipt, value, definitions) && score(value.score)
  && (value.raw_score == null || score(value.raw_score)) && feedback(value.feedback, count)
  && value.feedback.length === count
