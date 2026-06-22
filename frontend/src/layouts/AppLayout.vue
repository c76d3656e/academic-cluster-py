<script setup lang="ts">
import { ref } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import AppSidebar from '@/components/sidebar/AppSidebar.vue'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'

const { isMobile } = useBreakpoint()
const sheetOpen = ref(false)
</script>

<template>
  <!-- Mobile: Sheet sidebar -->
  <div v-if="isMobile" class="flex flex-col min-h-screen bg-background">
    <header class="flex items-center gap-3 px-4 py-3 border-b border-border shrink-0">
      <Sheet v-model:open="sheetOpen">
        <SheetTrigger as-child>
          <Button variant="ghost" size="icon" class="shrink-0">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="4" x2="20" y1="12" y2="12" />
              <line x1="4" x2="20" y1="6" y2="6" />
              <line x1="4" x2="20" y1="18" y2="18" />
            </svg>
          </Button>
        </SheetTrigger>
        <SheetContent side="left" class="w-[260px] p-0">
          <AppSidebar @navigate="sheetOpen = false" />
        </SheetContent>
      </Sheet>
      <router-link to="/console/overview" class="text-sm font-semibold text-foreground tracking-tight">
        Academic Cluster
      </router-link>
    </header>
    <div class="flex-1 min-w-0 overflow-x-hidden">
      <router-view />
    </div>
  </div>

  <!-- Desktop/Tablet: Static sidebar -->
  <div v-else class="flex min-h-screen bg-background">
    <AppSidebar />
    <div class="flex-1 min-w-0">
      <router-view />
    </div>
  </div>
</template>
