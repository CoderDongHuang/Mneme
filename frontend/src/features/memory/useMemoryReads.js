import useIndependentRead from '../../hooks/useIndependentRead'
import { endpoints } from '../../api/client'
import { validManagedMemories, validPendingMemories } from './memoryReadValidation'

const selectMemories = value => value.memories
const identity = value => value
export default function useMemoryReads() {
  const items = useIndependentRead(endpoints.managedMemories, validManagedMemories, selectMemories)
  const pending = useIndependentRead(endpoints.pendingMemories, validPendingMemories, identity)
  return { items, pending }
}
