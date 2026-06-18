<script setup lang="ts">
const store = useMissionStore()
const username = ref('admin')
const password = ref('')
const loginError = ref<string | null>(null)
const submitting = ref(false)

onMounted(async () => {
  await store.restoreAdminSession()
  if (store.isAdmin) await navigateTo('/')
})

async function login() {
  loginError.value = null
  submitting.value = true
  try {
    await store.loginAdmin(username.value, password.value)
    await navigateTo('/')
  } catch (err) {
    loginError.value = err instanceof Error ? err.message : 'ログインできませんでした'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="page admin-login">
    <h1>Administrator Login</h1>
    <form class="panel form-panel admin-login__form" @submit.prevent="login">
      <div v-if="loginError" class="error">{{ loginError }}</div>
      <label>
        Username
        <input v-model="username" name="username" autocomplete="username">
      </label>
      <label>
        Password
        <input v-model="password" name="password" type="password" autocomplete="current-password">
      </label>
      <button :disabled="submitting" type="submit">{{ submitting ? 'Signing in...' : 'Login' }}</button>
    </form>
  </main>
</template>
