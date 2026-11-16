import type { User } from '../api/auth'

export function getUserInitials(user: User): string {
  const initials = user.full_name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
  return initials.toUpperCase() || user.email[0]?.toUpperCase() || 'U'
}
