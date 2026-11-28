import { expect, test } from 'vitest'
import contract from '../../../contracts/quiz.schema.json'
import cases from '../../../contracts/quiz.cases.json'
import { matchesSchema } from './schemaContract'
import { validAttempts, validDraft, validQuiz, validSubmission } from '../features/quiz/quizValidation'

test.each(cases)('shares Java and browser quiz REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'Quiz') expect(validQuiz(data)).toBe(valid)
  if (schema === 'QuizDraft') expect(validDraft(data, 1)).toBe(valid)
  if (schema === 'QuizAttempt') expect(validAttempts([data], 1)).toBe(valid)
  if (schema === 'QuizSubmissionReceipt') expect(validSubmission(data, 1)).toBe(valid)
})
