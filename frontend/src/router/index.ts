import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const LoginView = () => import('../views/LoginView.vue')
const ProjectsView = () => import('../views/ProjectsView.vue')
const MapWorkspaceView = () => import('../views/MapWorkspaceView.vue')
const AppLayout = () => import('../layouts/AppLayout.vue')
const AdminDashboardView = () => import('../views/admin/AdminDashboardView.vue')
const DataCatalogView = () => import('../views/admin/DataCatalogView.vue')
const BatchImportView = () => import('../views/admin/BatchImportView.vue')
const DatasetCleanupView = () => import('../views/admin/DatasetCleanupView.vue')
const ImportJobsView = () => import('../views/admin/ImportJobsView.vue')
const ProjectManagementView = () => import('../views/admin/ProjectManagementView.vue')
const UserManagementView = () => import('../views/admin/UserManagementView.vue')
const SystemManagementView = () => import('../views/admin/SystemManagementView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/map/:id', name: 'map', component: MapWorkspaceView },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/projects' },
        { path: 'projects', name: 'projects', component: ProjectsView, meta: { title: '项目门户' } },
        { path: 'admin', name: 'admin', component: AdminDashboardView, meta: { admin: true, title: '管理概览' } },
        { path: 'admin/users', name: 'admin-users', component: UserManagementView, meta: { admin: true, title: '用户管理' } },
        { path: 'admin/projects', name: 'admin-projects', component: ProjectManagementView, meta: { admin: true, title: '项目管理' } },
        { path: 'admin/data', name: 'admin-data', component: DataCatalogView, meta: { admin: true, title: '数据目录' } },
        { path: 'admin/batch-imports', name: 'admin-batch-imports', component: BatchImportView, meta: { admin: true, title: '批量导入' } },
        { path: 'admin/data-cleanup', name: 'admin-data-cleanup', component: DatasetCleanupView, meta: { admin: true, title: '数据清理' } },
        { path: 'admin/jobs', name: 'admin-jobs', component: ImportJobsView, meta: { admin: true, title: '导入任务' } },
        { path: 'admin/system', name: 'admin-system', component: SystemManagementView, meta: { admin: true, title: '图层与系统' } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.bootstrap()
  if (to.meta.public) {
    return auth.isAuthenticated && to.name === 'login' ? '/projects' : true
  }
  if (!auth.isAuthenticated) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return '/projects'
  return true
})

export default router
