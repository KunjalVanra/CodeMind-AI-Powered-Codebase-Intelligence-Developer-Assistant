import {
  Bot,
  GitBranch,
  LayoutDashboard,
  Search,
  Settings,
  Sparkles,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { getUserInitials } from '../../auth/userDisplay'

const navigation = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard, end: true },
  { label: 'Repositories', to: '/repositories', icon: GitBranch },
  { label: 'Code Search', to: '/search', icon: Search },
  { label: 'AI Assistant', to: '/assistant', icon: Bot },
]

type SidebarProps = {
  onNavigate?: () => void
}

function Sidebar({ onNavigate }: SidebarProps) {
  const { user } = useAuth()

  return (
    <aside className="sidebar">
      <NavLink
        className="brand"
        to="/"
        aria-label="CodeMind dashboard"
        onClick={onNavigate}
      >
        <span className="brand-mark">
          <Sparkles size={20} strokeWidth={2.2} />
        </span>
        <span className="brand-copy">
          <strong>CodeMind</strong>
          <span>Codebase Intelligence</span>
        </span>
      </NavLink>

      <div className="sidebar-section-label">Workspace</div>
      <nav className="sidebar-nav" aria-label="Main navigation">
        {navigation.map(({ label, to, icon: Icon, end }) => (
          <NavLink
            key={to}
            className={({ isActive }) =>
              `nav-link${isActive ? ' nav-link-active' : ''}`
            }
            to={to}
            end={end}
            onClick={onNavigate}
          >
            <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
            {label === 'AI Assistant' && <span className="nav-new">AI</span>}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <NavLink
          className={({ isActive }) =>
            `nav-link${isActive ? ' nav-link-active' : ''}`
          }
          to="/settings"
          onClick={onNavigate}
        >
          <Settings size={18} strokeWidth={1.8} aria-hidden="true" />
          <span>Settings</span>
        </NavLink>
        <div className="sidebar-profile">
          <span className="avatar avatar-sidebar" aria-hidden="true">
            {user ? getUserInitials(user) : 'U'}
          </span>
          <span className="profile-copy">
            <strong>{user?.full_name ?? 'Account'}</strong>
            <span>{user?.email ?? ''}</span>
          </span>
          {user?.is_active && (
            <span className="profile-status" aria-label="Active account" />
          )}
        </div>
      </div>
    </aside>
  )
}

export default Sidebar
