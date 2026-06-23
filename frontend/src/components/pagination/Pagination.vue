<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-vue-next'
import type { PaginationProps, PaginationState } from './types'

const props = withDefaults(defineProps<PaginationProps>(), {
  showFirstLast: true,
  showPrevNext: true,
  showPageNumbers: true,
  maxVisiblePages: 5,
  disabled: false,
  size: 'md',
})

const { t } = useI18n()

// 计算分页状态
const paginationState = computed<PaginationState>(() => {
  const { currentPage, totalPages, maxVisiblePages } = props

  // 计算可见页码范围
  let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2))
  let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1)

  // 调整起始页码
  if (endPage - startPage + 1 < maxVisiblePages) {
    startPage = Math.max(1, endPage - maxVisiblePages + 1)
  }

  // 生成页码数组
  const pages: number[] = []
  for (let i = startPage; i <= endPage; i++) {
    pages.push(i)
  }

  return {
    currentPage,
    totalPages,
    pages,
    hasPrevious: currentPage > 1,
    hasNext: currentPage < totalPages,
    hasFirst: startPage > 1,
    hasLast: endPage < totalPages,
  }
})

// 计算按钮尺寸
const buttonSize = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'sm'
    case 'md':
      return 'default'
    case 'lg':
      return 'lg'
    default:
      return 'default'
  }
})

// 跳转到指定页
function goToPage(page: number) {
  if (page < 1 || page > props.totalPages || page === props.currentPage || props.disabled) {
    return
  }
  props.onPageChange(page)
}

// 跳转到第一页
function goToFirstPage() {
  goToPage(1)
}

// 跳转到上一页
function goToPreviousPage() {
  goToPage(props.currentPage - 1)
}

// 跳转到下一页
function goToNextPage() {
  goToPage(props.currentPage + 1)
}

// 跳转到最后一页
function goToLastPage() {
  goToPage(props.totalPages)
}
</script>

<template>
  <nav
    class="flex items-center justify-center gap-1"
    :aria-label="t('pagination.label')"
  >
    <!-- 第一页按钮 -->
    <Button
      v-if="showFirstLast"
      variant="outline"
      :size="buttonSize"
      :disabled="!paginationState.hasFirst || disabled"
      :aria-label="t('pagination.first')"
      @click="goToFirstPage"
    >
      <ChevronsLeft class="h-4 w-4" />
    </Button>

    <!-- 上一页按钮 -->
    <Button
      v-if="showPrevNext"
      variant="outline"
      :size="buttonSize"
      :disabled="!paginationState.hasPrevious || disabled"
      :aria-label="t('pagination.previous')"
      @click="goToPreviousPage"
    >
      <ChevronLeft class="h-4 w-4" />
    </Button>

    <!-- 页码按钮 -->
    <template v-if="showPageNumbers">
      <!-- 第一页（如果不在可见范围内） -->
      <Button
        v-if="paginationState.hasFirst"
        variant="outline"
        :size="buttonSize"
        :disabled="disabled"
        @click="goToPage(1)"
      >
        1
      </Button>

      <!-- 省略号（前面） -->
      <span
        v-if="paginationState.hasFirst && paginationState.pages[0] > 2"
        class="px-2 text-muted-foreground"
      >
        ...
      </span>

      <!-- 可见页码 -->
      <Button
        v-for="page in paginationState.pages"
        :key="page"
        :variant="page === currentPage ? 'default' : 'outline'"
        :size="buttonSize"
        :disabled="disabled"
        :aria-current="page === currentPage ? 'page' : undefined"
        @click="goToPage(page)"
      >
        {{ page }}
      </Button>

      <!-- 省略号（后面） -->
      <span
        v-if="paginationState.hasLast && paginationState.pages[paginationState.pages.length - 1] < totalPages - 1"
        class="px-2 text-muted-foreground"
      >
        ...
      </span>

      <!-- 最后一页（如果不在可见范围内） -->
      <Button
        v-if="paginationState.hasLast"
        variant="outline"
        :size="buttonSize"
        :disabled="disabled"
        @click="goToPage(totalPages)"
      >
        {{ totalPages }}
      </Button>
    </template>

    <!-- 下一页按钮 -->
    <Button
      v-if="showPrevNext"
      variant="outline"
      :size="buttonSize"
      :disabled="!paginationState.hasNext || disabled"
      :aria-label="t('pagination.next')"
      @click="goToNextPage"
    >
      <ChevronRight class="h-4 w-4" />
    </Button>

    <!-- 最后一页按钮 -->
    <Button
      v-if="showFirstLast"
      variant="outline"
      :size="buttonSize"
      :disabled="!paginationState.hasLast || disabled"
      :aria-label="t('pagination.last')"
      @click="goToLastPage"
    >
      <ChevronsRight class="h-4 w-4" />
    </Button>
  </nav>
</template>
