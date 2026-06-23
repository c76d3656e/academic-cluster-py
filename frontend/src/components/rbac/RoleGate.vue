<script setup lang="ts">
import { computed } from 'vue'
import type { RoleGateProps } from './types'

const props = withDefaults(defineProps<RoleGateProps>(), {
  requiredRoles: () => [],
  requiredPermissions: () => [],
  fallback: false,
})

// 检查用户是否拥有所需角色
const hasRequiredRoles = computed(() => {
  if (props.requiredRoles.length === 0) return true
  return props.requiredRoles.some((roleName) =>
    props.user.roles.some((role) => role.name === roleName)
  )
})

// 检查用户是否拥有所需权限
const hasRequiredPermissions = computed(() => {
  if (props.requiredPermissions.length === 0) return true
  return props.requiredPermissions.every((permissionName) =>
    props.user.roles.some((role) =>
      role.permissions.some((permission) => permission.name === permissionName)
    )
  )
})

// 计算是否有访问权限
const hasAccess = computed(() => {
  return hasRequiredRoles.value && hasRequiredPermissions.value
})
</script>

<template>
  <slot v-if="hasAccess" />
  <slot v-else-if="fallback" name="fallback" />
</template>
