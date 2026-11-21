export interface AdminSession {
  authenticated: true
  username: string
  csrf_token: string
  expires_at: string
}
