import { X } from 'lucide-react'
import Sidebar from './Sidebar'

type MobileNavigationProps = {
  isOpen: boolean
  onClose: () => void
}

function MobileNavigation({ isOpen, onClose }: MobileNavigationProps) {
  if (!isOpen) return null

  return (
    <div className="mobile-navigation">
      <button
        className="mobile-navigation-backdrop"
        type="button"
        aria-label="Close navigation menu"
        onClick={onClose}
      />
      <div className="mobile-navigation-panel">
        <button
          className="mobile-close-button"
          type="button"
          aria-label="Close navigation menu"
          onClick={onClose}
        >
          <X size={19} />
        </button>
        <Sidebar onNavigate={onClose} />
      </div>
    </div>
  )
}

export default MobileNavigation
