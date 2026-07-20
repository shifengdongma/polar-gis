import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL,
  withCredentials: true,
  timeout: 30_000,
})

let accessToken: string | null = null
let refreshPromise: Promise<string> | null = null

function toSnakeCase(value: string) {
  return value.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)
}

export function setAccessToken(token: string | null) {
  accessToken = token
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (config.params && !(config.params instanceof URLSearchParams)) {
    config.params = Object.fromEntries(
      Object.entries(config.params).map(([key, value]) => [toSnakeCase(key), value]),
    )
  }
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    if (!config || error.response?.status !== 401 || config._retried || config.url?.includes('/auth/')) {
      return Promise.reject(error)
    }
    config._retried = true
    refreshPromise ??= api
      .post<{ accessToken: string }>('/auth/refresh')
      .then((response) => {
        setAccessToken(response.data.accessToken)
        return response.data.accessToken
      })
      .finally(() => {
        refreshPromise = null
      })
    const token = await refreshPromise
    config.headers.Authorization = `Bearer ${token}`
    return api(config)
  },
)

export function apiErrorMessage(error: unknown, fallback = '操作失败') {
  if (axios.isAxiosError(error)) {
    return (error.response?.data as { message?: string } | undefined)?.message || fallback
  }
  return fallback
}
