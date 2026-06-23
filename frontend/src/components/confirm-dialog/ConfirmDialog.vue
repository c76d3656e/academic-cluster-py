<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/i18n'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Loader2, AlertTriangle } from 'lucide-vue-next'
import type { ConfirmDialogProps } from './types'

const props = withDefaults(defineProps<ConfirmDialogProps>(), {
  description: undefined,
  confirmLabel: 'Confirm',
  cancelLabel: 'Cancel',
  variant: 'default',
  onConfirm: undefined,
  onCancel: undefined,
  loading: false,
})

const { t } = useI18n()

const isOpen = ref(false)
const isLoading = ref(false)

// 打开对话框
function open() {
  isOpen.value = true
}

// 关闭对话框
function close() {
  isOpen.value = false
}

// 确认操作
async function handleConfirm() {
  if (!props.onConfirm) {
    close()
    return
  }

  isLoading.value = true
  try {
    await props.onConfirm()
    close()
  } finally {
    isLoading.value = false
  }
}

// 取消操作
function handleCancel() {
  props.onCancel?.()
  close()
}

// 暴露方法给父组件
defineExpose({
  open,
  close,
})
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent>
      <DialogHeader>
        <div class="flex items-center gap-3">
          <div
            v-if="variant === 'destructive'"
            class="flex-shrink-0 w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center"
          >
            <AlertTriangle class="h-5 w-5 text-destructive" />
          </div>
          <div>
            <DialogTitle>{{ title }}</DialogTitle>
            <DialogDescription v-if="description">
              {{ description }}
            </DialogDescription>
          </div>
        </div>
      </DialogHeader>
      <DialogFooter>
        <Button
          variant="outline"
          :disabled="isLoading || loading"
          @click="handleCancel"
        >
          {{ cancelLabel }}
        </Button>
        <Button
          :variant="variant === 'destructive' ? 'destructive' : 'default'"
          :disabled="isLoading || loading"
          @click="handleConfirm"
        >
          <Loader2 v-if="isLoading || loading" class="mr-2 h-4 w-4 animate-spin" />
          {{ confirmLabel }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
