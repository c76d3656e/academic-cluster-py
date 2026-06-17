import { ref, computed, nextTick, shallowRef } from 'vue'
import { projectsApi, type ReviewResponse, type WrittenSection, type EvidenceCard, type Outline } from '@/api/projects'

export function useProjectReview(projectId: string) {
  const reviewData = ref<ReviewResponse | null>(null)
  const isLoadingReview = shallowRef(false)

  const outline = computed<Outline | null>(() => reviewData.value?.outline ?? null)
  const sections = computed<WrittenSection[]>(() => reviewData.value?.sections ?? [])
  const evidenceCards = computed<EvidenceCard[]>(() => reviewData.value?.evidence_cards ?? [])
  const references = computed(() => reviewData.value?.references ?? [])

  const hasReview = computed(() =>
    reviewData.value && reviewData.value.sections && reviewData.value.sections.length > 0
  )

  const totalWordCount = computed(() =>
    sections.value.reduce((sum, s) => sum + (s.word_count ?? 0), 0)
  )

  const uniqueClusters = computed(() => {
    const ids = new Set(evidenceCards.value.map(c => c.cluster_id).filter(Boolean))
    return ids.size
  })

  const articleAbstract = computed(() => {
    if (reviewData.value?.abstract) return reviewData.value.abstract.trim()
    if (!sections.value.length) return ''
    const firstContent = sections.value[0].content || ''
    const paragraphs = firstContent.split(/\n\n+/).filter(p => p.trim() && !p.trim().startsWith('#'))
    return paragraphs[0]?.trim() || ''
  })

  const evidenceCardByPaperId = computed(() => {
    const map: Record<string, EvidenceCard> = {}
    for (const card of evidenceCards.value) {
      if (card.paper_id && !map[card.paper_id]) map[card.paper_id] = card
    }
    return map
  })

  async function loadReview() {
    try {
      isLoadingReview.value = true
      reviewData.value = await projectsApi.getReview(projectId)
      if (reviewData.value?.sections?.length) {
        await nextTick()
      }
    } catch {
      // review may not exist yet
    } finally {
      isLoadingReview.value = false
    }
  }

  return {
    reviewData, isLoadingReview, outline, sections, evidenceCards, references,
    hasReview, totalWordCount, uniqueClusters, articleAbstract, evidenceCardByPaperId,
    loadReview
  }
}
