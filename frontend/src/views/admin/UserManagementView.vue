<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { api, apiErrorMessage } from '../../api/client'
import type { Paginated, User } from '../../types'

const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(15)
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ username: '', displayName: '', password: '', role: 'user' })
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 120, message: '用户名长度为 3 至 120 个字符', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_.@-]+$/, message: '用户名仅支持字母、数字和 . _ @ -', trigger: 'blur' },
  ],
  displayName: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  password: [{ required: true, message: '请输入初始密码', trigger: 'blur' }, { min: 8, max: 256, message: '密码至少需要 8 个字符', trigger: 'blur' }],
}

async function loadUsers(targetPage = page.value) {
  loading.value = true
  try {
    const response = await api.get<Paginated<User>>('/admin/users', { params: { page: targetPage, pageSize: pageSize.value } })
    users.value = response.data.items
    total.value = response.data.total
    page.value = response.data.page
  } finally {
    loading.value = false
  }
}

async function createUser() {
  const valid = await formRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await api.post('/admin/users', form)
    ElMessage.success('用户创建成功')
    dialogVisible.value = false
    Object.assign(form, { username: '', displayName: '', password: '', role: 'user' })
    await loadUsers(1)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '用户创建失败'))
  } finally {
    saving.value = false
  }
}

async function toggleUser(user: User) {
  try {
    await api.patch(`/admin/users/${user.id}`, { isActive: !user.isActive })
    ElMessage.success(user.isActive ? '用户已停用' : '用户已启用')
    await loadUsers()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

onMounted(loadUsers)
</script>

<template>
  <div class="page-stack">
    <section class="page-intro compact">
      <div><span class="eyebrow">ACCESS CONTROL</span><h2>用户管理</h2><p>管理系统管理员和普通用户。</p></div>
      <el-button type="primary" @click="dialogVisible = true">创建用户</el-button>
    </section>
    <el-card shadow="never" class="data-card">
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column prop="displayName" label="显示名称" min-width="160" />
        <el-table-column label="角色" width="140">
          <template #default="{ row }"><el-tag :type="row.role === 'system_admin' ? 'primary' : 'info'">{{ row.role === 'system_admin' ? '系统管理员' : '普通用户' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><span :class="['status-pill', row.isActive ? 'success' : 'muted']">{{ row.isActive ? '启用' : '停用' }}</span></template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="180">
          <template #default="{ row }">{{ row.lastLoginAt ? new Date(row.lastLoginAt).toLocaleString('zh-CN') : '从未登录' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="right">
          <template #default="{ row }"><el-button link :type="row.isActive ? 'danger' : 'primary'" @click="toggleUser(row)">{{ row.isActive ? '停用' : '启用' }}</el-button></template>
        </el-table-column>
      </el-table>
      <div v-if="total" class="table-pagination"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadUsers" @size-change="loadUsers(1)" /></div>
    </el-card>
    <el-dialog v-model="dialogVisible" title="创建用户" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="用户名" prop="username"><el-input v-model="form.username" placeholder="3 至 120 个字符" /></el-form-item>
        <el-form-item label="显示名称" prop="displayName"><el-input v-model="form.displayName" /></el-form-item>
        <el-form-item label="初始密码" prop="password"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 8 个字符" /></el-form-item>
        <el-form-item label="角色" prop="role"><el-select v-model="form.role" class="full-width"><el-option label="普通用户" value="user" /><el-option label="系统管理员" value="system_admin" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="createUser">创建</el-button></template>
    </el-dialog>
  </div>
</template>
