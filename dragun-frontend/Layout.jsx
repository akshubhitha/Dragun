import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import FAB from './FAB.jsx'
import ChipModal from './ChipModal.jsx'
import { useState, useCallback } from 'react'
import { logout as apiLogout, deleteAccount, exportData } from '../api.js'

export default function Layout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  const [chipModal, setChipModal] = useState(null) // { category } or null

  const handleLogout = async () => {
    try { await apiLogout(session.user_id) } catch {}
    logout()
    navigate('/login', { replace: true })
  }

  const handleDeleteAccount = async () => {
    if (!confirm('Delete your account?\n\nYour spending data stays as anonymous records — your name and email are permanently removed. This can\'t be undone.')) return
    try { await deleteAccount(session.user_id) } catch {}
    logout()
    navigate('/login', { replace: true })
  }

  const handleExport = async () => {
    try {
      const data = await exportData(session.user_id)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `dragun-export-${new Date().toISOString().slice(0,10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { alert(e.message) }
  }

  const openChip = useCallback((cat) => setChipModal({ category: cat }), [])
  const closeChip = useCallback(() => setChipModal(null), [])

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <nav className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            dragun
            <span>@{session.handle || '—'}</span>
          </div>
        </div>

        <button className="ask-cta" onClick={() => navigate('/chat')}>
          <i className="ti ti-message-circle-2" />
          <div>
            <span>Ask Dragun</span>
            <span className="cta-sub">log · ask · explore</span>
          </div>
        </button>

        <div className="nav">
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/" end>
            <i className="ti ti-home" />Overview
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/spending">
            <i className="ti ti-chart-bar" />Spending
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/budgets">
            <i className="ti ti-wallet" />Budgets
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/goals">
            <i className="ti ti-target" />Goals
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/guards">
            <i className="ti ti-shield-check" />Guards
          </NavLink>

          <div className="nav-section-label">More</div>

          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/inventory">
            <i className="ti ti-package" />Inventory
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`} to="/settings">
            <i className="ti ti-settings" />Settings
          </NavLink>
        </div>

        <div className="sidebar-footer">
          <button className="logout-btn" onClick={handleLogout}>
            <i className="ti ti-logout" style={{ fontSize: 14 }} />Sign out
          </button>
          <button className="logout-btn danger" onClick={handleDeleteAccount}>
            <i className="ti ti-trash" style={{ fontSize: 14 }} />Delete account
          </button>
          <button className="logout-btn" onClick={handleExport}>
            <i className="ti ti-download" style={{ fontSize: 14 }} />Export data
          </button>
        </div>
      </nav>

      {/* ── Main ── */}
      <div className="main">
        <div className="content">
          <Outlet context={{ openChip }} />
        </div>
      </div>

      {/* ── Overlays ── */}
      <FAB onClick={() => navigate('/chat')} />
      {chipModal && (
        <ChipModal
          category={chipModal.category}
          userId={session.user_id}
          onClose={closeChip}
        />
      )}
    </div>
  )
}
