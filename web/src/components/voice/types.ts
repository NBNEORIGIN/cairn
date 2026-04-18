export type Location = 'workshop' | 'office' | 'home'
export type Mode = 'chat' | 'voice'

export interface MeResponse {
  authenticated: boolean
  user?: { email: string; name?: string | null; role: string }
  allowed_locations?: Location[]
  login_url?: string
}
