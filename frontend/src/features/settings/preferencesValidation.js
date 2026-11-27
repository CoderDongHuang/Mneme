import preferencesContract from '../../../../contracts/preferences.schema.json'
import { matchesSchema } from '../../api/schemaContract'

export function validPreferences(value) {
  if (!matchesSchema(preferencesContract.$defs.Preferences, value, preferencesContract.$defs)) return false
  try {
    new Intl.DateTimeFormat('en', { timeZone: value.timezone })
    return true
  } catch {
    return false
  }
}
