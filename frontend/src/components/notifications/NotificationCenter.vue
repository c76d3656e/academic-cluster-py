<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Bell, Check, CheckCheck, Trash2, ExternalLink } from 'lucide-vue-next'
import type { NotificationCenterProps, Notification } from './types'

const props = withDefaults(defineProps<NotificationCenterProps>(), {
  onMarkAsRead: undefined,
  onMarkAllAsRead: undefined,
  onDelete: undefined,
  onClearAll: undefined,
})

const { t } = useI18n()

// 计算未读数量
const unreadCount = computed(() => {
  return props.notifications.filter((n) => !n.read).length
})

// 按日期分组通知
const groupedNotifications = computed(() => {
  const groups: { label: string; notifications: Notification[] }[] = []
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000)
  const lastWeek = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)

  const todayNotifications: Notification[] = []
  const yesterdayNotifications: Notification[] = []
  const lastWeekNotifications: Notification[] = []
  const olderNotifications: Notification[] = []

  for (const notification of props.notifications) {
    const date = new Date(notification.timestamp)
    if (date >= today) {
      todayNotifications.push(notification)
    } else if (date >= yesterday) {
      yesterdayNotifications.push(notification)
    } else if (date >= lastWeek) {
      lastWeekNotifications.push(notification)
    } else {
      olderNotifications.push(notification)
    }
  }

  if (todayNotifications.length > 0) {
    groups.push({ label: t('notifications.today'), notifications: todayNotifications })
  }
  if (yesterdayNotifications.length > 0) {
    groups.push({ label: t('notifications.yesterday'), notifications: yesterdayNotifications })
  }
  if (lastWeekNotifications.length > 0) {
    groups.push({ label: t('notifications.lastWeek'), notifications: lastWeekNotifications })
  }
  if (olderNotifications.length > 0) {
    groups.push({ label: t('notifications.older'), notifications: olderNotifications })
  }

  return groups
})

// 获取通知类型颜色
function getNotificationTypeColor(type: string) {
  switch (type) {
    case 'success':
      return 'bg-green-100 text-green-800'
    case 'warning':
      return 'bg-yellow-100 text-yellow-800'
    case 'error':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-blue-100 text-blue-800'
  }
}

// 计算相对时间
function relativeTime(date: Date): string {
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (seconds < 60) return t('notifications.justNow')
  if (minutes < 60) return t('notifications.minutesAgo', { count: minutes })
  if (hours < 24) return t('notifications.hoursAgo', { count: hours })
  if (days < 7) return t('notifications.daysAgo', { count: days })
  return date.toLocaleDateString()
}

// 标记为已读
function markAsRead(id: string) {
  props.onMarkAsRead?.(id)
}

// 标记所有为已读
function markAllAsRead() {
  props.onMarkAllAsRead?.()
}

// 删除通知
function deleteNotification(id: string) {
  props.onDelete?.(id)
}

// 清空所有通知
function clearAll() {
  props.onClearAll?.()
}
</script>

<template>
  <Card class="w-full max-w-md">
    <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
      <div class="flex items-center gap-2">
        <Bell class="h-5 w-5" />
        <CardTitle class="text-lg">{{ t('notifications.title') }}</CardTitle>
        <Badge v-if="unreadCount > 0" variant="default">
          {{ unreadCount }}
        </Badge>
      </div>
      <div class="flex items-center gap-2">
        <Button
          v-if="unreadCount > 0"
          variant="ghost"
          size="sm"
          @click="markAllAsRead"
        >
          <CheckCheck class="h-4 w-4 mr-1" />
          {{ t('notifications.markAllRead') }}
        </Button>
        <Button
          v-if="notifications.length > 0"
          variant="ghost"
          size="sm"
          @click="clearAll"
        >
          <Trash2 class="h-4 w-4 mr-1" />
          {{ t('notifications.clearAll') }}
        </Button>
      </div>
    </CardHeader>
    <CardContent>
      <div v-if="notifications.length === 0" class="text-center py-8 text-muted-foreground">
        <Bell class="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>{{ t('notifications.empty') }}</p>
      </div>

      <div v-else class="space-y-4">
        <div v-for="group in groupedNotifications" :key="group.label">
          <div class="text-sm font-medium text-muted-foreground mb-2">
            {{ group.label }}
          </div>
          <div class="space-y-2">
            <div
              v-for="notification in group.notifications"
              :key="notification.id"
              class="flex items-start gap-3 p-3 rounded-lg border"
              :class="{ 'bg-muted/50': !notification.read }"
            >
              <Badge :class="getNotificationTypeColor(notification.type)">
                {{ notification.type }}
              </Badge>
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between">
                  <div class="font-medium">{{ notification.title }}</div>
                  <div class="flex items-center gap-1">
                    <span class="text-xs text-muted-foreground">
                      {{ relativeTime(notification.timestamp) }}
                    </span>
                    <Button
                      v-if="!notification.read"
                      variant="ghost"
                      size="sm"
                      class="h-6 w-6 p-0"
                      @click="markAsRead(notification.id)"
                    >
                      <Check class="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-6 w-6 p-0"
                      @click="deleteNotification(notification.id)"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                <div class="text-sm text-muted-foreground mt-1">
                  {{ notification.message }}
                </div>
                <div v-if="notification.action" class="mt-2">
                  <Button variant="link" size="sm" class="h-auto p-0" as-child>
                    <a :href="notification.action.href">
                      {{ notification.action.label }}
                      <ExternalLink class="h-3 w-3 ml-1" />
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
