export interface SocialProvider {
  id: string
  name: string
  icon: string
  color: string
  enabled: boolean
}

export interface SocialLoginProps {
  providers: SocialProvider[]
  onLogin?: (providerId: string) => void
  disabled?: boolean
}
