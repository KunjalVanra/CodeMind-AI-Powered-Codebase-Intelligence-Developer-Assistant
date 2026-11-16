import { Settings } from 'lucide-react'

function SettingsPage() {
  return (
    <section className="placeholder-page page-enter">
      <div className="placeholder-icon icon-purple"><Settings size={23} /></div>
      <span className="eyebrow">Workspace</span>
      <h1>Settings</h1>
      <p>
        Workspace preferences and configuration will be available here in a
        later milestone.
      </p>
    </section>
  )
}

export default SettingsPage
