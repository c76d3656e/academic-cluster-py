<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Separator } from '@/components/ui/separator'
import { useI18n } from '@/i18n'
import { formatRuntime } from '@/lib/utils'
import type { WrittenSection, EvidenceCard, Outline } from '@/api/projects'

const { t } = useI18n()

const props = defineProps<{
  outline: Outline | null
  sections: WrittenSection[]
  references: Array<{
    new_number: number
    original_number: number
    paper_id: string
    title?: string
    authors?: string
    venue?: string
    year?: string
    doi?: string
  }>
  evidenceCards: EvidenceCard[]
  evidenceCardByPaperId: Record<string, EvidenceCard>
  totalWordCount: number
  uniqueClusters: number
  articleAbstract: string
  projectQuery: string
  projectCreatedAt?: string
  projectStatus: string
}>()

/** Ordered outline section titles */
const outlineTitles = computed<string[]>(() => {
  if (!props.outline?.sections) return []
  return props.outline.sections.map((s) => s.title ?? s.heading ?? s.id ?? '')
})

/** Render a single section content as sanitized HTML with citation links */
function renderSection(content: string): string {
  if (!content) return ''
  let cleaned = content
    .replace(/\(\s*\[(\d+)\]\s*\)/g, '[$1]')
    .replace(/\(\s*\[x\]\s*\)/gi, '')
    .replace(/（\s*\[(\d+)\]\s*）/g, '[$1]')
    .replace(/（\s*\[x\]\s*）/gi, '')
  let html = marked.parse(cleaned) as string
  html = html.replace(/\[(\d+(?:[,、]\s*\d+)*)\]/g, (_, nums: string) => {
    return nums
      .split(/[,、]\s*/)
      .map((n: string) => `<sup class="cite-ref"><a href="#ref-${n.trim()}" title="Reference ${n.trim()}">[${n.trim()}]</a></sup>`)
      .join('')
  })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['title'] })
}

/** Get display title for a written section */
function getSectionTitle(section: WrittenSection, idx: number): string {
  if (idx < outlineTitles.value.length && outlineTitles.value[idx]) {
    return outlineTitles.value[idx]
  }
  const sid = section.section_id
  return sid.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Table of contents items */
const tocItems = computed(() => {
  return props.sections.map((s, i) => ({
    idx: i,
    title: getSectionTitle(s, i),
  }))
})

/** Active section index for ToC highlighting */
const activeSection = ref(-1)
let observer: IntersectionObserver | null = null

function setupSectionObserver() {
  if (observer) observer.disconnect()
  const ids = props.sections.map((_, i) => `section-${i}`)
  ids.push('references')
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const id = entry.target.id
          if (id === 'references') {
            activeSection.value = -2
          } else {
            const idx = parseInt(id.replace('section-', ''), 10)
            if (!isNaN(idx)) activeSection.value = idx
          }
        }
      }
    },
    { rootMargin: '-80px 0px -60% 0px', threshold: 0 }
  )
  for (const id of ids) {
    const el = document.getElementById(id)
    if (el) observer.observe(el)
  }
}

onMounted(() => {
  if (props.sections.length) setupSectionObserver()
})

onUnmounted(() => {
  if (observer) { observer.disconnect(); observer = null }
})

/** Scroll to a section by index */
function scrollToSection(idx: number) {
  const el = document.getElementById(`section-${idx}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** Scroll to references section */
function scrollToReferences() {
  const el = document.getElementById('references')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="flex flex-col lg:flex-row gap-8 py-6">
    <!-- Main Article Column -->
    <article class="flex-1 min-w-0 max-w-[780px]">
      <!-- Article Header -->
      <header class="mb-6">
        <h1 class="text-[1.65rem] md:text-[1.85rem] font-bold leading-snug tracking-tight text-foreground mb-3">
          {{ outline?.title || projectQuery }}
        </h1>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{{ totalWordCount.toLocaleString() }} {{ t('common.words') }}</span>
          <span class="text-muted-foreground/30">&middot;</span>
          <span>{{ t('article.sections', { count: sections.length }) }}</span>
          <span class="text-muted-foreground/30">&middot;</span>
          <span>{{ t('article.evidenceCardsCount', { count: evidenceCards.length }) }}</span>
          <span v-if="projectCreatedAt && (projectStatus === 'completed' || projectStatus === 'failed' || projectStatus === 'interrupted')" class="text-muted-foreground/30">&middot;</span>
          <span v-if="projectCreatedAt && (projectStatus === 'completed' || projectStatus === 'failed' || projectStatus === 'interrupted')" class="tabular-nums">
            {{ t('pipeline.runtime', { time: formatRuntime(projectCreatedAt) }) }}
          </span>
          <span v-if="uniqueClusters > 0" class="text-muted-foreground/30">&middot;</span>
          <span v-if="uniqueClusters > 0">{{ t('article.clusters', { count: uniqueClusters }) }}</span>
          <span class="text-muted-foreground/30">&middot;</span>
          <span>{{ projectCreatedAt ? new Date(projectCreatedAt).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '' }}</span>
        </div>
      </header>

      <!-- Abstract -->
      <div v-if="articleAbstract" class="mb-8 pl-4 border-l-[3px] border-foreground/10">
        <h2 class="text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-1.5">{{ t('article.abstract') }}</h2>
        <p class="text-[0.875rem] leading-[1.8] text-foreground/80">
          {{ articleAbstract }}
        </p>
      </div>

      <Separator class="mb-8" />

      <!-- Article Body -->
      <div class="nature-article">
        <section
          v-for="(section, idx) in sections"
          :key="section.id"
          :id="`section-${idx}`"
          class="mb-10 scroll-mt-20"
        >
          <h2 class="nature-section-heading">
            <a :href="`#section-${idx}`" class="section-anchor" @click.prevent="scrollToSection(idx)">
              <span class="section-num">{{ idx + 1 }}</span>
              {{ getSectionTitle(section, idx) }}
            </a>
          </h2>
          <div
            class="nature-prose"
            v-html="renderSection(section.content)"
          ></div>
        </section>
      </div>

      <!-- References Section -->
      <Separator class="my-10" />
      <section id="references" class="mb-16 scroll-mt-20">
        <h2 class="text-lg font-semibold text-foreground tracking-tight mb-6">{{ t('article.references') }}</h2>
        <ol class="space-y-4">
          <li
            v-for="(ref, idx) in references"
            :key="`${ref.paper_id || idx}-${ref.new_number || idx}`"
            :id="`ref-${idx + 1}`"
            class="ref-card scroll-mt-20"
          >
            <div class="flex gap-3">
              <span class="ref-num">{{ idx + 1 }}</span>
              <div class="flex-1 min-w-0 space-y-1.5">
                <p v-if="ref.title" class="text-[0.8125rem] font-medium text-foreground leading-relaxed">
                  {{ ref.title }}
                </p>
                <div class="flex flex-wrap gap-x-3 gap-y-1 text-[0.6875rem] text-muted-foreground">
                  <span v-if="ref.authors"><b class="text-foreground/40">{{ t('article.authors') }}:</b> {{ ref.authors }}</span>
                  <span v-if="ref.venue"><b class="text-foreground/40">{{ t('article.venue') }}:</b> {{ ref.venue }}</span>
                  <span v-if="ref.year"><b class="text-foreground/40">{{ t('article.year') }}:</b> {{ ref.year }}</span>
                  <span v-if="ref.doi"><b class="text-foreground/40">{{ t('article.doi') }}:</b> {{ ref.doi }}</span>
                </div>
                <div v-if="evidenceCardByPaperId[ref.paper_id]" class="mt-2 pl-3 border-l-2 border-border/50 space-y-1">
                  <p class="text-[0.6875rem] text-foreground/80 leading-relaxed">
                    <b class="text-foreground/40">{{ t('article.claim') }}:</b> {{ evidenceCardByPaperId[ref.paper_id].claim }}
                  </p>
                  <p v-if="evidenceCardByPaperId[ref.paper_id].method" class="text-[0.6875rem] text-muted-foreground">
                    <b class="text-foreground/40">{{ t('article.method') }}:</b> {{ evidenceCardByPaperId[ref.paper_id].method }}
                  </p>
                  <p v-if="evidenceCardByPaperId[ref.paper_id].metric" class="text-[0.6875rem] text-muted-foreground">
                    <b class="text-foreground/40">{{ t('article.metric') }}:</b> {{ evidenceCardByPaperId[ref.paper_id].metric }}
                  </p>
                  <p v-if="evidenceCardByPaperId[ref.paper_id].limitation" class="text-[0.6875rem] text-muted-foreground">
                    <b class="text-foreground/40">{{ t('article.limitation') }}:</b> {{ evidenceCardByPaperId[ref.paper_id].limitation }}
                  </p>
                </div>
              </div>
            </div>
          </li>
        </ol>
      </section>
    </article>

    <!-- Sidebar: TOC -->
    <aside class="hidden lg:block w-[220px] lg:w-[240px] shrink-0">
      <div class="sticky top-16 space-y-6">
        <div>
          <h3 class="text-[0.6rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-2.5">{{ t('article.contents') }}</h3>
          <nav class="space-y-px">
            <a
              v-for="item in tocItems"
              :key="item.idx"
              :href="`#section-${item.idx}`"
              class="toc-link"
              :class="{ 'toc-active': activeSection === item.idx }"
              @click.prevent="scrollToSection(item.idx)"
            >
              <span class="toc-num">{{ item.idx + 1 }}</span>
              {{ item.title }}
            </a>
            <a
              href="#references"
              class="toc-link"
              :class="{ 'toc-active': activeSection === -2 }"
              @click.prevent="scrollToReferences"
            >
              <span class="toc-num">R</span>
              {{ t('article.references') }}
            </a>
          </nav>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
/* ============================================ */
/* Nature-style section headings                */
/* ============================================ */
.nature-section-heading {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--foreground);
  margin-bottom: 0.75rem;
  letter-spacing: -0.01em;
  line-height: 1.35;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.section-num {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--muted-foreground);
  opacity: 0.5;
  min-width: 1.25rem;
}

.section-anchor {
  color: inherit;
  text-decoration: none;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  transition: opacity 0.15s;
}

.section-anchor:hover {
  opacity: 0.75;
}

.section-anchor:hover .section-num {
  opacity: 0.8;
}

/* ============================================ */
/* Nature-style prose rendering                 */
/* ============================================ */
.nature-prose :deep(h1) {
  font-size: 1.375rem;
  font-weight: 700;
  margin-top: 2rem;
  margin-bottom: 0.625rem;
  color: var(--foreground);
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.nature-prose :deep(h2) {
  font-size: 1.125rem;
  font-weight: 600;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
  color: var(--foreground);
  letter-spacing: -0.01em;
  line-height: 1.35;
}

.nature-prose :deep(h3) {
  font-size: 1rem;
  font-weight: 600;
  margin-top: 1.25rem;
  margin-bottom: 0.375rem;
  color: var(--foreground);
}

.nature-prose :deep(p) {
  font-size: 0.875rem;
  line-height: 1.85;
  margin-bottom: 0.875rem;
  color: var(--foreground);
  text-align: justify;
  text-indent: 2em;
}

.nature-prose :deep(ul),
.nature-prose :deep(ol) {
  font-size: 0.875rem;
  line-height: 1.75;
  margin-bottom: 0.875rem;
  padding-left: 1.5em;
  color: var(--foreground);
}

.nature-prose :deep(li) {
  margin-bottom: 0.25rem;
}

.nature-prose :deep(strong) {
  font-weight: 600;
  color: var(--foreground);
}

.nature-prose :deep(em) {
  font-style: italic;
}

.nature-prose :deep(blockquote) {
  border-left: 2px solid var(--border);
  padding-left: 1rem;
  margin: 1rem 0;
  color: var(--muted-foreground);
  font-style: italic;
  font-size: 0.875rem;
}

.nature-prose :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1.25rem 0;
  font-size: 0.8125rem;
}

.nature-prose :deep(th) {
  background: var(--muted);
  font-weight: 600;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--border);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--muted-foreground);
}

.nature-prose :deep(td) {
  padding: 0.375rem 0.625rem;
  border: 1px solid var(--border);
  vertical-align: top;
}

.nature-prose :deep(tr:nth-child(even)) {
  background: var(--muted);
}

.nature-prose :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1.5rem 0;
}

.nature-prose :deep(a) {
  color: var(--foreground);
  text-decoration: underline;
  text-underline-offset: 2px;
  text-decoration-color: var(--border);
}

.nature-prose :deep(a:hover) {
  text-decoration-color: var(--foreground);
}

.nature-prose :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.8em;
  background: var(--muted);
  padding: 0.1em 0.35em;
  border-radius: 3px;
}

.nature-prose :deep(pre) {
  background: var(--muted);
  padding: 0.875rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: 1rem 0;
  border: 1px solid var(--border);
}

.nature-prose :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: 0.8rem;
  line-height: 1.6;
}

.nature-prose :deep(img) {
  max-width: 100%;
  border-radius: 6px;
  margin: 0.75rem 0;
}

/* Citation superscript links */
.nature-prose :deep(sup.cite-ref) {
  font-size: 0.7em;
  line-height: 0;
  position: relative;
  vertical-align: baseline;
  top: -0.45em;
}

.nature-prose :deep(sup.cite-ref a) {
  color: var(--foreground);
  text-decoration: none;
  font-weight: 500;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.nature-prose :deep(sup.cite-ref a:hover) {
  opacity: 1;
  text-decoration: underline;
}

/* ============================================ */
/* Table of Contents sidebar                    */
/* ============================================ */
.toc-link {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
  padding: 0.25rem 0;
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--muted-foreground);
  text-decoration: none;
  transition: color 0.15s;
  border-left: 2px solid transparent;
  padding-left: 0.5rem;
}

.toc-link:hover {
  color: var(--foreground);
  border-left-color: var(--border);
}

.toc-active {
  color: var(--foreground);
  font-weight: 500;
  border-left-color: var(--foreground);
  background: var(--muted);
  border-radius: 0 4px 4px 0;
}

.toc-num {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  opacity: 0.45;
  min-width: 1rem;
  flex-shrink: 0;
}

/* ============================================ */
/* Reference cards                              */
/* ============================================ */
.ref-card {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
}

.ref-card:last-child {
  border-bottom: none;
}

.ref-num {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--muted-foreground);
  opacity: 0.45;
  min-width: 1.5rem;
  text-align: right;
  flex-shrink: 0;
  padding-top: 0.125rem;
}
</style>
