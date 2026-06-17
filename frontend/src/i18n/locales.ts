import { zh } from './zh'

export type Locale = 'zh' | 'en'

export type Messages = typeof zh

export type NestedKeyOf<T> = T extends object
  ? { [K in keyof T]: T[K] extends object ? `${K & string}.${NestedKeyOf<T[K]>}` : K & string }[keyof T]
  : never

export type TranslationKey = NestedKeyOf<Messages>

export const localeOptions: { value: Locale; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
]
