<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { api } from '../../api/client'
import type { Dataset, ImportJob, Paginated, Project, User } from '../../types'

const stats = reactive({ users: 0, projects: 0, datasets: 0, activeJobs: 0 })

onMounted(async () => {
  const [users, projects, datasets, jobs] = await Promise.all([
    api.get<Paginated<User>>('/admin/users', { params: { pageSize: 1 } }),
    api.get<Paginated<Project>>('/admin/projects', { params: { pageSize: 1 } }),
    api.get<Paginated<Dataset>>('/admin/datasets', { params: { pageSize: 1 } }),
    api.get<Paginated<ImportJob>>('/admin/import-jobs', { params: { pageSize: 100 } }),
  ])
  stats.users = users.data.total
  stats.projects = projects.data.total
  stats.datasets = datasets.data.total
  stats.activeJobs = jobs.data.items.filter((job) => ['queued', 'running'].includes(job.status)).length
})
</script>

<template>
  <div class="page-stack">
    <section class="page-intro">
      <div>
        <span class="eyebrow">SYSTEM OVERVIEW</span>
        <h2>管理概览</h2>
        <p>查看平台资源和数据处理状态。</p>
      </div>
    </section>
    <div class="stat-grid">
      <article class="stat-card"><span>系统用户</span><strong>{{ stats.users }}</strong><small>两个角色</small></article>
      <article class="stat-card"><span>项目总数</span><strong>{{ stats.projects }}</strong><small>草稿与已发布</small></article>
      <article class="stat-card"><span>数据集</span><strong>{{ stats.datasets }}</strong><small>可复用数据目录</small></article>
      <article class="stat-card accent"><span>活动任务</span><strong>{{ stats.activeJobs }}</strong><small>排队或处理中</small></article>
    </div>
    <el-alert
      title="非认证航海信息系统"
      description="平台用于海图与环境信息展示，不替代ECDIS或法定航海设备。"
      type="warning"
      :closable="false"
      show-icon
    />
  </div>
</template>

