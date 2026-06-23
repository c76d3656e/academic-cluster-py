<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Search, X, Command } from 'lucide-vue-next'
import type { SearchResult, SearchSource, GlobalSearchProps } from './types'

const props = withDefaults(defineProps<GlobalSearchProps>(), {
  placeholder: 'Search...',
  inline: false,
  limitPerGroup: 6,
})

const router = useRouter()
const { t } = useI18n()

const isOpen = ref(false)
const query = ref('')
const selectedIndex = ref(0)

// 计算搜索结果
const searchResults = computed(() => {
  if (!query.value.trim()) return []

  const results: { source: SearchSource; results: SearchResult[] }[] = []

  for (const source of props.sources) {
    let sourceResults: SearchResult[]

    if (source.search) {
      sourceResults = source.search(query.value)
    } else {
      const mappedItems = source.items.map(source.toResult)
      sourceResults = defaultMatch(mappedItems, query.value)
    }

    // 限制每组结果数量
    sourceResults = sourceResults.slice(0, props.limitPerGroup)

    if (sourceResults.length > 0) {
      results.push({ source, results: sourceResults })
    }
  }

  return results
})

// 默认匹配函数
function defaultMatch(items: SearchResult[], query: string): SearchResult[] {
  const lowerQuery = query.toLowerCase()
  return items.filter((item) => {
    const haystack = `${item.title} ${item.subtitle ?? ''}`.toLowerCase()
    return haystack.includes(lowerQuery)
  })
}

// 计算所有结果的扁平列表（用于键盘导航）
const allResults = computed(() => {
  return searchResults.value.flatMap((group) => group.results)
})

// 打开搜索对话框
function openSearch() {
  isOpen.value = true
  query.value = ''
  selectedIndex.value = 0
}

// 关闭搜索对话框
function closeSearch() {
  isOpen.value = false
  query.value = ''
  selectedIndex.value = 0
}

// 选择结果
function selectResult(result: SearchResult) {
  closeSearch()
  router.push(result.href)
}

// 键盘快捷键处理
function handleKeydown(e: KeyboardEvent) {
  // Cmd+K / Ctrl+K 打开搜索
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    if (isOpen.value) {
      closeSearch()
    } else {
      openSearch()
    }
    return
  }

  if (!isOpen.value) return

  switch (e.key) {
    case 'Escape':
      e.preventDefault()
      closeSearch()
      break
    case 'ArrowUp':
      e.preventDefault()
      selectedIndex.value = Math.max(0, selectedIndex.value - 1)
      break
    case 'ArrowDown':
      e.preventDefault()
      selectedIndex.value = Math.min(allResults.value.length - 1, selectedIndex.value + 1)
      break
    case 'Enter':
      e.preventDefault()
      if (allResults.value[selectedIndex.value]) {
        selectResult(allResults.value[selectedIndex.value])
      }
      break
  }
}

// 监听查询变化，重置选中索引
watch(query, () => {
  selectedIndex.value = 0
})

// 注册全局键盘事件
onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <!-- 内联模式 -->
  <div v-if="inline" class="w-full">
    <div class="relative">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
      <Input
        v-model="query"
        :placeholder="placeholder"
        class="pl-10 pr-4"
        @focus="openSearch"
      />
    </div>

    <!-- 搜索结果面板 -->
    <Card v-if="isOpen && query.trim()" class="absolute z-50 w-full mt-1 max-h-[400px] overflow-auto">
      <CardContent class="p-0">
        <div v-if="allResults.length === 0" class="p-4 text-center text-muted-foreground">
          {{ t('search.noResults') }}
        </div>

        <template v-for="group in searchResults" :key="group.source.label">
          <div class="px-2 py-1.5 text-xs font-medium text-muted-foreground bg-muted/50">
            {{ group.source.label }} · {{ group.results.length }}
          </div>
          <div
            v-for="result in group.results"
            :key="result.id"
            class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent"
            :class="{ 'bg-accent': allResults.indexOf(result) === selectedIndex }"
            @click="selectResult(result)"
            @mouseenter="selectedIndex = allResults.indexOf(result)"
          >
            <div class="flex-1 min-w-0">
              <div class="font-medium truncate">{{ result.title }}</div>
              <div v-if="result.subtitle" class="text-sm text-muted-foreground truncate">
                {{ result.subtitle }}
              </div>
            </div>
          </div>
        </template>
      </CardContent>
    </Card>
  </div>

  <!-- 对话框模式 -->
  <div v-else>
    <!-- 触发按钮 -->
    <Button
      variant="outline"
      class="w-full justify-start text-muted-foreground"
      @click="openSearch"
    >
      <Search class="mr-2 h-4 w-4" />
      <span>{{ placeholder }}</span>
      <Badge variant="secondary" class="ml-auto">
        <Command class="h-3 w-3" />K
      </Badge>
    </Button>

    <!-- 搜索对话框 -->
    <Teleport to="body">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      >
        <!-- 遮罩层 -->
        <div class="fixed inset-0 bg-black/50" @click="closeSearch" />

        <!-- 搜索面板 -->
        <Card class="relative z-50 w-full max-w-xl mx-4">
          <CardContent class="p-0">
            <!-- 搜索输入 -->
            <div class="flex items-center gap-3 px-4 py-3 border-b">
              <Search class="h-4 w-4 text-muted-foreground" />
              <Input
                v-model="query"
                :placeholder="placeholder"
                class="flex-1 border-0 shadow-none focus-visible:ring-0"
                autofocus
              />
              <Badge variant="secondary" class="text-xs">
                Esc
              </Badge>
            </div>

            <!-- 搜索结果 -->
            <div class="max-h-[400px] overflow-auto">
              <div v-if="!query.trim()" class="p-4 text-center text-muted-foreground">
                {{ t('search.startTyping') }}
              </div>

              <div v-else-if="allResults.length === 0" class="p-4 text-center text-muted-foreground">
                {{ t('search.noResults') }}
              </div>

              <template v-else>
                <template v-for="group in searchResults" :key="group.source.label">
                  <div class="px-2 py-1.5 text-xs font-medium text-muted-foreground bg-muted/50">
                    {{ group.source.label }} · {{ group.results.length }}
                  </div>
                  <div
                    v-for="result in group.results"
                    :key="result.id"
                    class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent"
                    :class="{ 'bg-accent': allResults.indexOf(result) === selectedIndex }"
                    @click="selectResult(result)"
                    @mouseenter="selectedIndex = allResults.indexOf(result)"
                  >
                    <div class="flex-1 min-w-0">
                      <div class="font-medium truncate">{{ result.title }}</div>
                      <div v-if="result.subtitle" class="text-sm text-muted-foreground truncate">
                        {{ result.subtitle }}
                      </div>
                    </div>
                  </div>
                </template>
              </template>
            </div>
          </CardContent>
        </Card>
      </div>
    </Teleport>
  </div>
</template>
