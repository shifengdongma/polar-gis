import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { MapConfig, Paginated, Project } from '../types'

export const useProjectsStore = defineStore('projects', () => {
  const projects = ref<Project[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(15)
  const loading = ref(false)

  async function loadProjects(search = '', order = 'desc', targetPage = page.value) {
    loading.value = true
    try {
      const response = await api.get<Paginated<Project>>('/projects', {
        params: { search: search || undefined, order, page: targetPage, pageSize: pageSize.value },
      })
      projects.value = response.data.items
      total.value = response.data.total
      page.value = response.data.page
    } finally {
      loading.value = false
    }
  }

  async function loadMapConfig(projectId: string) {
    const response = await api.get<MapConfig>(`/projects/${projectId}/map-config`)
    return response.data
  }

  return { projects, total, page, pageSize, loading, loadProjects, loadMapConfig }
})
