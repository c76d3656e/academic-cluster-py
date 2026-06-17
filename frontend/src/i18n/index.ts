import { shallowRef, computed } from 'vue'
import { zh } from './zh'
import { en } from './en'
import type { Locale, Messages } from './locales'

export type { Locale, Messages }
export { localeOptions } from './locales'

const messages: Record<Locale, Messages> = { zh, en }

const locale = shallowRef<Locale>((localStorage.getItem('locale') as Locale) || 'zh')

/**
 * Get a nested value from an object using a dot-separated path.
 * e.g. getNestedValue(obj, 'common.loading') => obj.common.loading
 */
function getNestedValue(obj: unknown, path: string): string | undefined {
  const keys = path.split('.')
  let current: unknown = obj
  for (const key of keys) {
    if (current === null || current === undefined || typeof current !== 'object') {
      return undefined
    }
    current = (current as Record<string, unknown>)[key]
  }
  return typeof current === 'string' ? current : undefined
}

export function useI18n() {
  const currentMessages = computed(() => messages[locale.value])

  /**
   * Translate a key with optional parameter substitution.
   * @param key - Dot-separated path like 'common.loading'
   * @param params - Optional parameters for interpolation, e.g. { name: 'test' }
   * @returns Translated string, or the key itself if not found
   */
  const t = (key: string, params?: Record<string, string | number>): string => {
    let result = getNestedValue(currentMessages.value, key)
    if (result === undefined) {
      // Fallback to Chinese if key not found in current locale
      if (locale.value !== 'zh') {
        result = getNestedValue(zh, key)
      }
      if (result === undefined) {
        return key
      }
    }

    // Parameter substitution: replace {param} with values
    if (params) {
      for (const [paramKey, paramValue] of Object.entries(params)) {
        result = result.replace(new RegExp(`\\{${paramKey}\\}`, 'g'), String(paramValue))
      }
    }

    return result
  }

  const setLocale = (newLocale: Locale) => {
    locale.value = newLocale
    localStorage.setItem('locale', newLocale)
  }

  return { locale, t, setLocale }
}
