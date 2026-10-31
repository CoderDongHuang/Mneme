import { usePreferences } from '../state/PreferencesContext'
import { dateKey, formatCalendarDate, formatDate, formatDateTime } from '../utils/dates'

export function useDateFormatter() {
  const { preferences } = usePreferences()
  const { language, timezone } = preferences
  return {
    dateTime: (value, options) => formatDateTime(value, language, timezone, options),
    date: (value, options) => formatDate(value, language, timezone, options),
    calendarDate: (value, options) => formatCalendarDate(value, language, options),
    dateKey: value => dateKey(value, timezone),
  }
}
