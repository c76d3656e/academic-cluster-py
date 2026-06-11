<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  class?: HTMLAttributes["class"]
}>()
</script>

<template>
  <tr
    data-slot="table-row"
    :class="cn('hover:bg-secondary/50 data-[state=selected]:bg-secondary border-b border-border transition-colors has-aria-expanded:bg-secondary/50', props.class)"
  >
    <slot />
  </tr>
</template>
