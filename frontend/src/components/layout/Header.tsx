import { Bell, LogOut, Menu } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { getUserInitials } from '../../auth/userDisplay'

const pageDetails: Record<string, { title: string; description: string }> = {
  '/': { title: 'Dashboard', description: 'Your codebase, at a glance.' },
  '/repositories': {
    title: 'Repositories',
    description: 'Manage the codebases in your workspace.',
  },
  '/search': {
    title: 'Code Search',
    description: 'Find relevant code with natural language.',
  },
  '/assistant': {
    title: 'AI Assistant',
    description: 'Ask questions grounded in your codebase.',
  },
  '/settings': {
    title: 'Settings',
    description: 'Workspace preferences and configuration.',
  },
}

type HeaderProps = {
  onMenuClick: () => void
}

function Header({ onMenuClick }: HeaderProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const page = pageDetails[pathname] ?? pageDetails['/']

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="topbar">
      <div className="topbar-heading">
        <button
          className="icon-button mobile-menu-button"
          type="button"
          aria-label="Open navigation menu"
          onClick={onMenuClick}
        >
          <Menu size={20} />
        </button>
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-current">{page.title}</span>
          </div>
          <p className="topbar-description">{page.description}</p>
        </div>
      </div>

      <div className="topbar-actions">
        <span className="icon-button notification-visual" aria-label="Notifications">
          <Bell size={18} strokeWidth={1.8} />
          <span className="notification-dot" />
        </span>
        <span className="topbar-divider" />
        <div className="topbar-profile">
          <span className="avatar avatar-header" aria-hidden="true">
            {user ? getUserInitials(user) : 'U'}
          </span>
          <span className="topbar-user-name">{user?.full_name ?? 'Account'}</span>
        </div>
        <button className="signout-button" type="button" onClick={handleLogout}>
          <LogOut size={15} />
          <span className="signout-label">Sign out</span>
        </button>
      </div>
    </header>
  )
}

export default Header
