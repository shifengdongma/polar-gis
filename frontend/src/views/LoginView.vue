<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiErrorMessage } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.push((route.query.redirect as string) || '/projects')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '用户名或密码错误'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="login-hero">
      <div class="hero-grid"></div>
      <div class="polar-orbit orbit-one"></div>
      <div class="polar-orbit orbit-two"></div>
      <div class="hero-copy">
        <span class="hero-kicker">POLAR MARINE INTELLIGENCE</span>
        <h1>看见海洋环境<br />理解极地变化</h1>
        <p>统一管理电子海图、遥感影像与环境专题数据，构建安全、清晰、可追溯的海洋空间信息底座。</p>
        <div class="hero-features">
          <span>S-57 海图</span>
          <span>北极投影</span>
          <span>空间查询</span>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <div class="login-logo">P</div>
        <span class="eyebrow">WELCOME BACK</span>
        <h2>登录极地海洋环境平台</h2>
        <p class="muted">使用系统管理员分配的账号登录</p>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入密码"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button type="primary" size="large" :loading="loading" class="full-button" @click="submit">
            登录系统
          </el-button>
        </el-form>
        <div class="legal-notice">本系统仅供信息展示与辅助分析，不替代法定航海设备。</div>
      </div>
    </section>
  </div>
</template>
