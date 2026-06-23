import { ref } from 'vue'
import type { ConfirmDialogOptions } from './types'

export function useConfirm() {
  const options = ref<ConfirmDialogOptions | null>(null)
  const resolvePromise = ref<((value: boolean) => void) | null>(null)

  function confirm(dialogOptions: ConfirmDialogOptions): Promise<boolean> {
    options.value = dialogOptions

    return new Promise<boolean>((resolve) => {
      resolvePromise.value = resolve
    })
  }

  function handleConfirm() {
    resolvePromise.value?.(true)
    options.value = null
    resolvePromise.value = null
  }

  function handleCancel() {
    resolvePromise.value?.(false)
    options.value = null
    resolvePromise.value = null
  }

  return {
    options,
    confirm,
    handleConfirm,
    handleCancel,
  }
}
