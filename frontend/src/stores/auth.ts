import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, setAccessToken } from '../api/client'
import type { User } from '../types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)
  const isAdmin = computed(() => user.value?.role === 'system_admin')
  const isAuthenticated = computed(() => Boolean(user.value))

  async function loadCurrentUser() {
    const response = await api.get<User>('/auth/me')
    user.value = response.data
  }

  async function login(username: string, password: string) {
    const response = await api.post<{ accessToken: string }>('/auth/login', { username, password })
    setAccessToken(response.data.accessToken)
    await loadCurrentUser()
  }

  async function bootstrap() {
    if (ready.value) return
    try {
      const response = await api.post<{ accessToken: string }>('/auth/refresh')
      setAccessToken(response.data.accessToken)
      await loadCurrentUser()
    } catch {
      setAccessToken(null)
      user.value = null
    } finally {
      ready.value = true
    }
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } finally {
      setAccessToken(null)
      user.value = null
      ready.value = true
    }
  }

  return { user, ready, isAdmin, isAuthenticated, login, bootstrap, logout }
})

