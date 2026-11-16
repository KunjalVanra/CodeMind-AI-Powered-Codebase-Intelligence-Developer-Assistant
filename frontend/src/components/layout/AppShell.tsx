import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Header from './Header'
import MobileNavigation from './MobileNavigation'
import Sidebar from './Sidebar'

function AppShell() {
  const [isMobileNavigationOpen, setIsMobileNavigationOpen] = useState(false)

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Header onMenuClick={() => setIsMobileNavigationOpen(true)} />
        <main className="page-content">
          <Outlet />
        </main>
      </div>
      <MobileNavigation
        isOpen={isMobileNavigationOpen}
        onClose={() => setIsMobileNavigationOpen(false)}
      />
    </div>
  )
}

export default AppShell
