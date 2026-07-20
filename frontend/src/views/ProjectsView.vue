<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { useProjectsStore } from '../stores/projects'

const router = useRouter()
const store = useProjectsStore()
const search = ref('')
const order = ref('desc')
let searchTimer: number | undefined

watch([search, order], () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => store.loadProjects(search.value, order.value, 1), 250)
})

onMounted(() => store.loadProjects())

function openProject(id: string) {
  router.push(`/map/${id}`)
}
</script>

<template>
  <div class="page-stack">
    <section class="page-intro">
      <div>
        <span class="eyebrow">PROJECT CATALOG</span>
        <h2>海洋环境项目</h2>
        <p>选择已发布项目，进入专业地图工作台。</p>
      </div>
      <div class="intro-stat">
        <strong>{{ store.total }}</strong>
        <span>已发布项目</span>
      </div>
    </section>

    <section class="toolbar-card">
      <el-input v-model="search" clearable :prefix-icon="Search" placeholder="按项目名称搜索" class="project-search" />
      <el-segmented v-model="order" :options="[{ label: '最新发布', value: 'desc' }, { label: '较早发布', value: 'asc' }]" />
    </section>

    <el-skeleton :loading="store.loading" animated :rows="5">
      <template #default>
        <div v-if="store.projects.length" class="project-grid">
          <article v-for="project in store.projects" :key="project.id" class="project-card" @click="openProject(project.id)">
            <div class="project-visual">
              <div class="latitude-line line-one"></div>
              <div class="latitude-line line-two"></div>
              <span class="project-code">{{ project.code.toUpperCase() }}</span>
              <span class="projection-badge">{{ project.defaultCrs === 'EPSG:3413' ? '北极投影' : '常规地图' }}</span>
            </div>
            <div class="project-body">
              <div class="project-title-row">
                <h3>{{ project.name }}</h3>
                <span class="arrow-link">→</span>
              </div>
              <p>{{ project.description || '暂无项目说明' }}</p>
              <div class="project-meta">
                <span><strong>{{ project.layerCount }}</strong> 个图层</span>
                <span>更新于 {{ new Date(project.updatedAt).toLocaleDateString('zh-CN') }}</span>
              </div>
            </div>
          </article>
        </div>
        <el-empty v-else description="没有符合条件的已发布项目" />
        <div v-if="store.total" class="table-pagination">
          <el-pagination v-model:current-page="store.page" v-model:page-size="store.pageSize" :page-sizes="[10, 15, 20, 50, 100]" :total="store.total" layout="total, sizes, prev, pager, next" @current-change="store.loadProjects(search, order)" @size-change="store.loadProjects(search, order, 1)" />
        </div>
      </template>
    </el-skeleton>
  </div>
</template>
