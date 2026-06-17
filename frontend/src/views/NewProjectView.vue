<script setup lang="ts">
import { shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { projectsApi } from '../api/projects'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from 'vue-sonner'

const router = useRouter()
const { t } = useI18n()

const name = shallowRef('')
const query = shallowRef('')
const description = shallowRef('')
const isSubmitting = shallowRef(false)

async function handleSubmit() {
  isSubmitting.value = true

  try {
    const project = await projectsApi.createProject({
      name: name.value,
      query: query.value,
      description: description.value || undefined,
    })
    toast.success(t('project.projectCreated'))
    router.push(`/projects/${project.id}`)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || t('project.projectCreateFailed'))
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-background">
    <header class="bg-background border-b border-border">
      <div class="container-standard px-4 md:px-6 py-4 flex items-center gap-3">
        <router-link to="/">
          <Button variant="ghost" size="sm">&larr; {{ t('common.back') }}</Button>
        </router-link>
        <h1 class="text-lg font-semibold tracking-tight truncate">{{ t('project.newProject') }}</h1>
      </div>
    </header>

    <main class="container-narrow px-6 py-10">
      <Card class="border border-border shadow-[var(--shadow-sm)]">
        <CardHeader>
          <CardTitle class="text-heading">{{ t('project.projectInfo') }}</CardTitle>
        </CardHeader>
        <CardContent>
          <form @submit.prevent="handleSubmit" class="space-y-6">
            <div class="space-y-2">
              <Label for="name">{{ t('project.projectName') }}</Label>
              <Input id="name" v-model="name" type="text" required :placeholder="t('project.projectNamePlaceholder')" />
            </div>

            <div class="space-y-2">
              <Label for="query">{{ t('project.query') }}</Label>
              <textarea
                id="query"
                v-model="query"
                required
                rows="3"
                class="flex w-full rounded-[var(--radius-lg)] border border-input bg-transparent px-3.5 py-2.5 text-base shadow-[var(--shadow-sm)] transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
                :placeholder="t('project.queryPlaceholder')"
              />
            </div>

            <div class="space-y-2">
              <Label for="description">{{ t('project.description') }}</Label>
              <textarea
                id="description"
                v-model="description"
                rows="2"
                class="flex w-full rounded-[var(--radius-lg)] border border-input bg-transparent px-3.5 py-2.5 text-base shadow-[var(--shadow-sm)] transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
                :placeholder="t('project.descriptionPlaceholder')"
              />
            </div>

            <Button type="submit" class="w-full h-10 rounded-[var(--radius-lg)]" :disabled="isSubmitting">
              {{ isSubmitting ? t('common.creating') : t('project.newProject') }}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  </div>
</template>
