export default defineNuxtConfig({
  ssr: true,
  modules: ['@pinia/nuxt'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000'
    }
  },
  css: ['~/assets/main.css'],
  typescript: {
    strict: true
  }
})
