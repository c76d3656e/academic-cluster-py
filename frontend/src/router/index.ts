import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/projects/new',
      name: 'new-project',
      component: () => import('../views/NewProjectView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/projects/:id',
      name: 'project-detail',
      component: () => import('../views/ProjectDetailView.vue'),
      meta: { requiresAuth: true },
    },
    // User Console
    {
      path: '/console',
      component: () => import('../layouts/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/console/overview' },
        {
          path: 'overview',
          name: 'console-overview',
          component: () => import('../views/console/ConsoleOverview.vue'),
        },
        {
          path: 'projects',
          name: 'console-projects',
          component: () => import('../views/console/ConsoleProjects.vue'),
        },
        // {
        //   path: 'usage',
        //   name: 'console-usage',
        //   component: () => import('../views/console/ConsoleUsage.vue'),
        // },
        {
          path: 'profile',
          name: 'console-profile',
          component: () => import('../views/console/ConsoleProfile.vue'),
        },
        {
          path: 'recharge',
          name: 'console-recharge',
          component: () => import('../views/console/ConsoleRecharge.vue'),
        },
      ],
    },
    // Admin Panel
    {
      path: '/admin',
      component: () => import('../layouts/AppLayout.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
      children: [
        { path: '', redirect: '/admin/overview' },
        {
          path: 'overview',
          name: 'admin-overview',
          component: () => import('../views/admin/AdminOverview.vue'),
        },
        {
          path: 'users',
          name: 'admin-users',
          component: () => import('../views/admin/AdminUsers.vue'),
        },
        {
          path: 'projects',
          name: 'admin-projects',
          component: () => import('../views/admin/AdminProjects.vue'),
        },
        {
          path: 'providers',
          name: 'admin-providers',
          component: () => import('../views/admin/AdminProviders.vue'),
        },
        {
          path: 'usage',
          name: 'admin-usage',
          component: () => import('../views/admin/AdminUsage.vue'),
        },
        {
          path: 'audit',
          name: 'admin-audit',
          component: () => import('../views/admin/AdminAudit.vue'),
        },
        {
          path: 'pipeline-config',
          name: 'admin-pipeline-config',
          component: () => import('../views/admin/AdminPipelineConfig.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: 'login' }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/' }
  }

  if (to.meta.guestOnly && auth.isAuthenticated) {
    return { path: '/' }
  }
})

export default router
