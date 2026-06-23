<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Plus, MoreHorizontal, GripVertical } from 'lucide-vue-next'
import type { KanbanProps, KanbanItem, KanbanColumn } from './types'

const props = withDefaults(defineProps<KanbanProps>(), {
  onItemMove: undefined,
  onItemCreate: undefined,
  onItemUpdate: undefined,
  onItemDelete: undefined,
  onColumnAdd: undefined,
  onColumnUpdate: undefined,
  onColumnDelete: undefined,
  draggable: true,
  editable: true,
})

const { t } = useI18n()

const draggedItem = ref<KanbanItem | null>(null)

// 按列分组 items
const itemsByColumn = computed(() => {
  const grouped: Record<string, KanbanItem[]> = {}

  for (const column of props.columns) {
    grouped[column.id] = props.items.filter((item) => item.status === column.status)
  }

  return grouped
})

// 获取优先级颜色
function getPriorityColor(priority?: string) {
  switch (priority) {
    case 'urgent':
      return 'bg-red-100 text-red-800'
    case 'high':
      return 'bg-orange-100 text-orange-800'
    case 'medium':
      return 'bg-yellow-100 text-yellow-800'
    case 'low':
      return 'bg-green-100 text-green-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}

// 获取用户头像首字母
function getInitials(name: string) {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

// 拖拽开始
function handleDragStart(item: KanbanItem) {
  if (!props.draggable) return
  draggedItem.value = item
}

// 拖拽结束
function handleDragEnd() {
  draggedItem.value = null
}

// 拖拽进入列
function handleDragEnter(column: KanbanColumn) {
  if (!draggedItem.value || !props.draggable) return

  const fromStatus = draggedItem.value.status
  const toStatus = column.status

  if (fromStatus !== toStatus) {
    props.onItemMove?.(draggedItem.value.id, fromStatus, toStatus)
  }
}

// 允许拖拽
function handleDragOver(e: DragEvent) {
  e.preventDefault()
}

// 添加新项目
function handleAddItem(columnId: string) {
  if (!props.editable) return

  const column = props.columns.find((c) => c.id === columnId)
  if (!column) return

  // 这里可以打开一个对话框来创建新项目
  // 为了简化，这里只是触发回调
  props.onItemCreate?.(columnId, {
    title: t('kanban.newItem'),
    status: column.status,
  })
}
</script>

<template>
  <div class="flex gap-4 overflow-x-auto p-4">
    <!-- 列 -->
    <div
      v-for="column in columns"
      :key="column.id"
      class="flex-shrink-0 w-80"
      @dragenter="handleDragEnter(column)"
      @dragover="handleDragOver"
    >
      <Card class="h-full">
        <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
          <div class="flex items-center gap-2">
            <div
              v-if="column.color"
              class="w-3 h-3 rounded-full"
              :style="{ backgroundColor: column.color }"
            />
            <CardTitle class="text-sm font-medium">{{ column.title }}</CardTitle>
            <Badge variant="secondary" class="text-xs">
              {{ itemsByColumn[column.id]?.length || 0 }}
            </Badge>
          </div>
          <div class="flex items-center gap-1">
            <Button
              v-if="editable"
              variant="ghost"
              size="sm"
              class="h-8 w-8 p-0"
              @click="handleAddItem(column.id)"
            >
              <Plus class="h-4 w-4" />
            </Button>
            <Button
              v-if="editable"
              variant="ghost"
              size="sm"
              class="h-8 w-8 p-0"
            >
              <MoreHorizontal class="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <!-- 项目列表 -->
          <div class="space-y-2">
            <div
              v-for="item in itemsByColumn[column.id]"
              :key="item.id"
              class="p-3 rounded-lg border bg-card hover:shadow-md transition-shadow cursor-move"
              :draggable="draggable"
              @dragstart="handleDragStart(item)"
              @dragend="handleDragEnd"
            >
              <div class="flex items-start justify-between">
                <div class="flex items-center gap-2">
                  <GripVertical v-if="draggable" class="h-4 w-4 text-muted-foreground" />
                  <div>
                    <div class="font-medium">{{ item.title }}</div>
                    <div v-if="item.description" class="text-sm text-muted-foreground mt-1">
                      {{ item.description }}
                    </div>
                  </div>
                </div>
                <Button
                  v-if="editable"
                  variant="ghost"
                  size="sm"
                  class="h-6 w-6 p-0"
                >
                  <MoreHorizontal class="h-3 w-3" />
                </Button>
              </div>

              <!-- 标签和优先级 -->
              <div class="flex items-center gap-2 mt-2">
                <Badge
                  v-if="item.priority"
                  :class="getPriorityColor(item.priority)"
                  class="text-xs"
                >
                  {{ item.priority }}
                </Badge>
                <Badge
                  v-for="tag in item.tags"
                  :key="tag"
                  variant="outline"
                  class="text-xs"
                >
                  {{ tag }}
                </Badge>
              </div>

              <!-- 底部信息 -->
              <div class="flex items-center justify-between mt-3">
                <div v-if="item.assignee" class="flex items-center gap-2">
                  <Avatar class="h-6 w-6">
                    <AvatarImage v-if="item.assignee.avatar" :src="item.assignee.avatar" />
                    <AvatarFallback class="text-xs">
                      {{ getInitials(item.assignee.name) }}
                    </AvatarFallback>
                  </Avatar>
                  <span class="text-xs text-muted-foreground">{{ item.assignee.name }}</span>
                </div>
                <div v-if="item.dueDate" class="text-xs text-muted-foreground">
                  {{ new Date(item.dueDate).toLocaleDateString() }}
                </div>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div
            v-if="!itemsByColumn[column.id]?.length"
            class="text-center py-8 text-muted-foreground"
          >
            <p class="text-sm">{{ t('kanban.noItems') }}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
