import sessionContract from '../../../contracts/chat-session.schema.json'
import baseContract from '../../../contracts/knowledge-base.schema.json'
import { matchesSchema } from './schemaContract'

const unique = (items, key) => new Set(items.map(item => item?.[key])).size === items.length
export const validBases = value => matchesSchema(baseContract.$defs.KnowledgeBaseList, value, baseContract.$defs)
  && unique(value, 'id') && value.every(item => item.name.trim())
export const validKnowledgeBase = value => validBases([value])
export const validSessions = value => matchesSchema(sessionContract.$defs.ChatSessionList, value, sessionContract.$defs) && unique(value, 'id')
