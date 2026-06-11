<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { projectsApi } from '../api/projects'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from 'vue-sonner'

const router = useRouter()

const name = ref('')
const query = ref('')
const description = ref('')
const isSubmitting = ref(false)

async function handleSubmit() {
  isSubmitting.value = true

  try {
    const project = await projectsApi.createProject({
      name: name.value,
      query: query.value,
      description: description.value || undefined,
    })
    toast.success('项目创建成功')
    router.push(`/projects/${project.id}`)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    toast.error(err.response?.data?.detail || '创建项目失败')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-muted/30">
    <header class="bg-background border-b">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
        <router-link to="/">
          <Button variant="ghost" size="sm">&larr; 返回</Button>
        </router-link>
        <h1 class="text-lg font-semibold">新建项目</h1>
      </div>
    </header>

    <main class="max-w-2xl mx-auto px-4 py-8">
      <Card>
        <CardHeader>
          <CardTitle>项目信息</CardTitle>
        </CardHeader>
        <CardContent>
          <form @submit.prevent="handleSubmit" class="space-y-6">
            <div class="space-y-2">
              <Label for="name">项目名称</Label>
              <Input id="name" v-model="name" type="text" required placeholder="例如：Transformer 综述" />
            </div>

            <div class="space-y-2">
              <Label for="query">研究主题 / 搜索查询</Label>
              <textarea
                id="query"
                v-model="query"
                required
                rows="3"
                class="flex w-full rounded-lg border border-input bg-transparent px-3 py-2 text-base shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
                placeholder="例如：transformer attention mechanism in deep learning"
              />
            </div>

            <div class="space-y-2">
              <Label for="description">描述（可选）</Label>
              <textarea
                id="description"
                v-model="description"
                rows="2"
                class="flex w-full rounded-lg border border-input bg-transparent px-3 py-2 text-base shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
                placeholder="项目的简要描述"
              />
            </div>

            <Button type="submit" class="w-full" :disabled="isSubmitting">
              {{ isSubmitting ? '创建中...' : '创建项目' }}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  </div>
</template>
