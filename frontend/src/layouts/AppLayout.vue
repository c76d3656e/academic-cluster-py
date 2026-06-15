<script setup lang="ts">
import AppSidebar from '@/components/sidebar/AppSidebar.vue'
</script>

<template>
  <div class="flex min-h-screen bg-background">
    <AppSidebar />
    <div class="flex-1 min-w-0">
      <router-view />
    </div>
  </div>
</template>
