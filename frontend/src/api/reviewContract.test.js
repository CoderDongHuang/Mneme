import { expect, test } from 'vitest'
import contract from '../../../contracts/review.schema.json'
import cases from '../../../contracts/review.cases.json'
import { matchesSchema } from './schemaContract'
import { validPlan, validReview } from '../features/review/reviewValidation'

test.each(cases)('shares the Java and browser review REST case $id', ({ schema, data, valid }) => {
  expect(matchesSchema(contract.$defs[schema], data, contract.$defs)).toBe(valid)
  if (schema === 'ReviewCard') expect(validReview(data)).toBe(valid)
  if (schema === 'LearningPlan') expect(validPlan(data)).toBe(valid)
})
