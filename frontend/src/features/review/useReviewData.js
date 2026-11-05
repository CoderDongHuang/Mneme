import { endpoints } from '../../api/client'
import useIndependentRead from '../../hooks/useIndependentRead'
import { validPlans, validReviews } from './reviewValidation'

export default function useReviewData() {
  const cards = useIndependentRead(endpoints.reviews, validReviews)
  const plans = useIndependentRead(endpoints.plans, validPlans)
  return { cards, plans }
}
