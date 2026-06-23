<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { MoreHorizontal, Loader2 } from 'lucide-vue-next'
import type { ActionMenuProps, ActionMenuItem } from './types'

const props = withDefaults(defineProps<ActionMenuProps>(), {
  trigger: 'click',
  align: 'end',
  side: 'bottom',
  disabled: false,
  loading: false,
})

const { t } = useI18n()

const isOpen = ref(false)
const loadingItemId = ref<string | null>(null)

// 处理项目点击
async function handleItemClick(item: ActionMenuItem) {
  if (item.disabled || props.disabled) return

  if (item.onClick) {
    loadingItemId.value = item.id
    try {
      await item.onClick()
    } finally {
      loadingItemId.value = null
    }
  }

  isOpen.value = false
}
</script>

<template>
  <DropdownMenu v-model:open="isOpen">
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="sm"
        class="h-8 w-8 p-0"
        :disabled="disabled"
      >
        <MoreHorizontal class="h-4 w-4" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent :align="align" :side="side">
      <template v-for="item in items" :key="item.id">
        <DropdownMenuSeparator v-if="item.separator" />
        <DropdownMenuItem
          :disabled="item.disabled || disabled"
          :class="{
            'text-destructive': item.destructive,
            'opacity-50': item.disabled,
          }"
          @click="handleItemClick(item)"
        >
          <div class="flex items-center gap-2">
            <Loader2
              v-if="loadingItemId === item.id"
              class="h-4 w-4 animate-spin"
            />
            <span v-else-if="item.icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
            <span
              v-if="item.shortcut"
              class="ml-auto text-xs text-muted-foreground"
            >
              {{ item.shortcut }}
            </span>
          </div>
        </DropdownMenuItem>
      </template>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
