import { shallowRef } from 'vue'
import { getFeatures, clearFeaturesCache, type Features } from '@/api/client'

/** Module-level singleton – shared across all components */
const features = shallowRef<Features>({ show_usage: false })
const isLoaded = shallowRef(false)

/**
 * Composable for reading backend feature flags.
 *
 * Because `features` and `isLoaded` are module-level refs they are shared
 * across every component that calls `useFeatures()`, so the API is only
 * hit once (unless `refreshFeatures` is called).
 */
export function useFeatures() {
  /** Load features from the API (no-op if already loaded) */
  async function loadFeatures(): Promise<Features> {
    if (isLoaded.value) return features.value
    features.value = await getFeatures()
    isLoaded.value = true
    return features.value
  }

  /** Force a re-fetch from the server */
  async function refreshFeatures(): Promise<Features> {
    clearFeaturesCache()
    isLoaded.value = false
    return loadFeatures()
  }

  return { features, isLoaded, loadFeatures, refreshFeatures }
}
