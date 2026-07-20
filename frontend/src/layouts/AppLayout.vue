<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  Compass,
  DataAnalysis,
  Delete,
  Files,
  Fold,
  House,
  Operation,
  Setting,
  SwitchButton,
  UploadFilled,
  User,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const activeMenu = computed(() => route.path)

async function logout() {
  await ElMessageBox.confirm('确定要退出当前账号吗？', '退出登录', {
    confirmButtonText: '退出',
    cancelButtonText: '取消',
    type: 'warning',
  })
  await auth.logout()
  await router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="brand">
        <div class="brand-mark"><el-icon><Compass /></el-icon></div>
        <div>
          <strong>POLAR GIS</strong>
          <span>极地海洋环境平台</span>
        </div>
      </div>
      <el-menu :default-active="activeMenu" router class="sidebar-menu">
        <el-menu-item index="/projects">
          <el-icon><House /></el-icon>
          <span>项目门户</span>
        </el-menu-item>
        <template v-if="auth.isAdmin">
          <div class="menu-caption">系统管理</div>
          <el-menu-item index="/admin">
            <el-icon><DataAnalysis /></el-icon>
            <span>管理概览</span>
          </el-menu-item>
          <el-menu-item index="/admin/users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/projects">
            <el-icon><Files /></el-icon>
            <span>项目管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/data">
            <el-icon><Operation /></el-icon>
            <span>数据目录</span>
          </el-menu-item>
          <el-menu-item index="/admin/batch-imports">
            <el-icon><UploadFilled /></el-icon>
            <span>批量导入</span>
          </el-menu-item>
          <el-menu-item index="/admin/data-cleanup">
            <el-icon><Delete /></el-icon>
            <span>数据清理</span>
          </el-menu-item>
          <el-menu-item index="/admin/jobs">
            <el-icon><Fold /></el-icon>
            <span>导入任务</span>
          </el-menu-item>
          <el-menu-item index="/admin/system">
            <el-icon><Setting /></el-icon>
            <span>图层与系统</span>
          </el-menu-item>
        </template>
      </el-menu>
      <div class="account-card">
        <span class="account-avatar">{{ auth.user?.displayName?.slice(0, 1) }}</span>
        <span class="account-copy">
          <strong>{{ auth.user?.displayName }}</strong>
          <small>{{ auth.isAdmin ? '系统管理员' : '普通用户' }}</small>
        </span>
        <el-tooltip content="退出登录" placement="top">
          <button class="account-logout" type="button" aria-label="退出登录" @click="logout">
            <el-icon><SwitchButton /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </aside>
    <main class="app-main">
      <header class="topbar">
        <div class="topbar-heading">
          <span class="topbar-product">POLAR GIS</span>
          <span class="topbar-separator">/</span>
          <strong>{{ route.meta.title || '工作台' }}</strong>
        </div>
        <div class="topbar-notice">
          <span class="status-dot"></span>
          非认证航海信息系统
        </div>
      </header>
      <section class="page-content">
        <RouterView />
      </section>
    </main>
  </div>
</template>
