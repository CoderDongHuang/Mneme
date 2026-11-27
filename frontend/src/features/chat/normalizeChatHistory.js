import historyContract from '../../../../contracts/chat-session.schema.json'
import sourceSchema from '../../../../contracts/chat-source.schema.json'
import { matchesSchema } from '../../api/schemaContract'

// These fields are read by the citation drawer and answer-copy action. Other
// parser metadata can retain historical formats, including CSV visual regions.
const displayedSourceFields = ['document_id', 'document_name', 'chunk_content', 'page', 'section',
  'retrieval_ranks', 'score', 'content_sha256', 'indexed_at', 'parser_version']

function validSource(source) {
  return source !== null && typeof source === 'object' && !Array.isArray(source)
    && displayedSourceFields.every(key => (source[key] == null && !sourceSchema.required.includes(key))
      || matchesSchema(sourceSchema.properties[key], source[key]))
}

export default function normalizeChatHistory(history, sessionId) {
  if (!matchesSchema(historyContract.$defs.ChatHistory, history, historyContract.$defs)
    || new Set(history.map(message => message.id)).size !== history.length
    || history.some(message => message.sessionId !== sessionId)) throw new Error('Invalid message history')

  let requestText
  return history.map(message => {
    let sources = message.sources ?? []
    if (message.sourcesJson) {
      try { sources = JSON.parse(message.sourcesJson) }
      catch { /* Older histories can contain opaque citation text. */ }
    }
    if (!Array.isArray(sources) || !sources.every(validSource)) throw new Error('Invalid history citations')
    if (message.role === 'user') requestText = message.content
    return {
      id: message.id, role: message.role, content: message.content,
      status: message.status === 'completed' ? 'complete' : (message.status || 'complete'),
      errorCode: message.errorCode, sources,
      requestText: message.role === 'assistant' ? requestText : undefined,
    }
  })
}
