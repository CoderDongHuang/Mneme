import contract from '../../../contracts/chat-stream.schema.json'

import { matchesSchema } from './schemaContract'

/** @param {keyof import('./generated/chat-stream').ChatStreamPayloads} event */
export function validChatEvent(event, payload) {
  return Object.hasOwn(contract.events, event) && matchesSchema(contract.events[event], payload, contract.$defs)
}
