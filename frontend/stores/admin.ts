import { defineStore } from 'pinia'
import type { AdminSession } from '~/types/api'

/** 管理者のセッション。書き換える操作には csrf_token を X-CSRF-Token に付けて送る。 */
export const useAdminStore = defineStore('admin', () => {
  const api = useApi()
  const adminSession = ref<AdminSession | null>(null)
  const isAdmin = computed(() => Boolean(adminSession.value?.authenticated))

  async function restoreAdminSession() {
    try {
      adminSession.value = await api.getAdminSession()
    } catch {
      adminSession.value = null // ログインしていない（401）
    }
  }

  async function loginAdmin(username: string, password: string) {
    adminSession.value = await api.loginAdmin({ username, password })
  }

  async function logoutAdmin() {
    const token = adminSession.value?.csrf_token
    if (!token) return
    await api.logoutAdmin(token)
    adminSession.value = null
  }

  return { adminSession, isAdmin, restoreAdminSession, loginAdmin, logoutAdmin }
})
