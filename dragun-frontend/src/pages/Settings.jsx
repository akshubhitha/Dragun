import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import {
  getMe, setHandle, saveProfile, exportData, deleteAccount,
  getConstraints, updateConstraint, deleteConstraint,
} from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(isoStr) {
  if (!isoStr) return null
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins  = Math.floor(diff / 60000)
  if (mins < 2)   return 'just now'
  if (mins < 60)  return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)   return `${hrs} hr ago`
  if (hrs < 48)   return 'Yesterday'
  return new Date(isoStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function constraintStatus(c) {
  if (!c.is_active) return 'paused'
  if (c.last_triggered_at) {
    const ms = Date.now() - new Date(c.last_triggered_at).getTime()
    if (ms < 24 * 60 * 60 * 1000) return 'triggered'
  }
  return 'ok'
}

const RULE_EMOJI = {
  dining: '🍽️', restaurants: '🍽️', coffee: '☕', groceries: '🛒',
  transport: '🚗', entertainment: '🎮', shopping: '🛍️', health: '💊',
}
function ruleEmoji(c) {
  const src = [...(c.scope_tags || []), c.item_normalized || ''].join(' ').toLowerCase()
  for (const [k, e] of Object.entries(RULE_EMOJI)) {
    if (src.includes(k)) return e
  }
  return '🛡️'
}

function ruleEmojiBg(c) {
  const src = [...(c.scope_tags || []), c.item_normalized || ''].join(' ').toLowerCase()
  if (src.includes('dining') || src.includes('restaurant')) return '#fde8e8'
  if (src.includes('coffee'))   return '#fef3e2'
  if (src.includes('groceries')) return '#f0f7f2'
  return '#f3f4f6'
}

function ruleName(c) {
  const tag  = c.scope_tags?.[0] || c.item_normalized || 'spending'
  const label = tag.charAt(0).toUpperCase() + tag.slice(1)
  const period = c.constraint_type?.includes('TREND') ? 'trend' : 'limit'
  return `${label} ${period}`
}

function ruleDesc(c) {
  const tag    = c.scope_tags?.[0] || c.item_normalized || 'spending'
  const amount = `$${Number(c.threshold_value || 0).toFixed(0)}`
  if (c.constraint_type === 'HARD_BUDGET_LIMIT') return `Alert when ${tag} exceeds ${amount}`
  if (c.constraint_type === 'VELOCITY_WARNING')   return `Alert if ${tag} pace exceeds ${amount}`
  if (c.constraint_type === 'TREND_ALERT')         return `Alert on unusual ${tag} trend (>${amount})`
  if (c.constraint_type === 'INVENTORY_CAP')       return `Cap ${tag} quantity`
  return c.message_template || `Rule: ${amount} limit on ${tag}`
}

// ── Toggle switch ─────────────────────────────────────────────────────────────

function Toggle({ checked, onChange }) {
  return (
    <label className="st-toggle" onClick={e => e.stopPropagation()}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <div className="st-toggle-track" />
      <div className="st-toggle-thumb" />
    </label>
  )
}

// ── Spending rule card ────────────────────────────────────────────────────────

function RuleCard({ c, onToggle, onDelete, onEdit }) {
  const status = constraintStatus(c)
  const trigged = relativeTime(c.last_triggered_at)

  return (
    <div className={`st-rule-card st-rule-card--${status}`}>
      <div className="st-rule-icon" style={{ background: ruleEmojiBg(c) }}>
        {ruleEmoji(c)}
      </div>
      <div className="st-rule-body">
        <div className="st-rule-name">
          {ruleName(c)}
          {status === 'triggered' && (
            <span className="st-rule-badge st-rule-badge--red">Triggered 🔴</span>
          )}
          {status === 'ok' && (
            <span className="st-rule-badge st-rule-badge--green">OK 🟢</span>
          )}
          {status === 'paused' && (
            <span className="st-rule-badge st-rule-badge--gray">Paused</span>
          )}
        </div>
        <div className="st-rule-desc">{ruleDesc(c)}</div>
        {status === 'triggered' && trigged && (
          <div className="st-rule-alert">Triggered {trigged}</div>
        )}
      </div>
      <div className="st-rule-controls">
        <button className="st-rule-edit" onClick={() => onEdit(c)}>Edit</button>
        <button className="st-rule-del" onClick={() => onDelete(c)}>✕</button>
        <Toggle checked={c.is_active} onChange={(val) => onToggle(c, val)} />
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Settings() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()

  // ── User data
  const [user,        setUser]        = useState(null)
  const [handle,      setHandleVal]   = useState(session.handle || '')
  const [currency,    setCurrency]    = useState('USD')
  const [income,      setIncome]      = useState('')
  const [savingHandle,   setSavingHandle]   = useState(false)
  const [savingProfile,  setSavingProfile]  = useState(false)
  const [handleMsg,      setHandleMsg]      = useState('')
  const [profileMsg,     setProfileMsg]     = useState('')

  // ── Constraints (spending rules)
  const [constraints, setConstraints] = useState([])

  // ── Notifications (local state — no backend)
  const [notifs, setNotifs] = useState({
    ruleAlerts:   true,
    budgetWarnings: true,
    weeklySummary:  false,
    goalMilestones: true,
  })

  // ── Section nav scroll spy
  const [activeSection, setActiveSection] = useState('account')

  useEffect(() => {
    async function load() {
      try {
        const [meRes, cRes] = await Promise.allSettled([
          getMe(session.user_id),
          getConstraints(session.user_id),
        ])
        if (meRes.status === 'fulfilled') {
          const u = meRes.value
          setUser(u)
          setHandleVal(u.handle || '')
          setCurrency(u.currency || 'USD')
          setIncome(u.monthly_income > 0 ? String(u.monthly_income) : '')
        }
        if (cRes.status === 'fulfilled') {
          setConstraints(cRes.value.constraints || [])
        }
      } catch {}
    }
    load()
  }, [session.user_id])

  // Scroll spy via IntersectionObserver — works regardless of which parent scrolls
  useEffect(() => {
    const ids = ['account', 'profile', 'rules', 'notifications', 'danger']
    const observers = []
    ids.forEach(id => {
      const el = document.getElementById(`st-${id}`)
      if (!el) return
      const obs = new IntersectionObserver(
        ([entry]) => { if (entry.isIntersecting) setActiveSection(id) },
        { threshold: 0.15 }
      )
      obs.observe(el)
      observers.push(obs)
    })
    return () => observers.forEach(o => o.disconnect())
  }, [])

  const scrollTo = (id) => {
    document.getElementById(`st-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // ── Account actions
  const handleSaveHandle = async () => {
    if (!handle.trim()) return
    setSavingHandle(true); setHandleMsg('')
    try {
      await setHandle(session.user_id, handle.trim())
      setHandleMsg('Saved ✓')
    } catch (e) {
      setHandleMsg(e.message || 'Error saving handle')
    } finally {
      setSavingHandle(false)
      setTimeout(() => setHandleMsg(''), 3000)
    }
  }

  const handleSaveProfile = async () => {
    setSavingProfile(true); setProfileMsg('')
    try {
      await saveProfile(session.user_id, {
        currency,
        monthly_income: parseFloat(income) || 0,
      })
      setProfileMsg('Saved ✓')
    } catch (e) {
      setProfileMsg(e.message || 'Error saving profile')
    } finally {
      setSavingProfile(false)
      setTimeout(() => setProfileMsg(''), 3000)
    }
  }

  // ── Constraint actions
  const handleToggleRule = async (c, val) => {
    setConstraints(prev => prev.map(x => x.constraint_id === c.constraint_id ? { ...x, is_active: val } : x))
    try {
      await updateConstraint(session.user_id, c.constraint_id, { is_active: val })
    } catch {
      // revert on error
      setConstraints(prev => prev.map(x => x.constraint_id === c.constraint_id ? { ...x, is_active: !val } : x))
    }
  }

  const handleDeleteRule = async (c) => {
    if (!confirm(`Delete the "${ruleName(c)}" rule?`)) return
    setConstraints(prev => prev.filter(x => x.constraint_id !== c.constraint_id))
    try {
      await deleteConstraint(session.user_id, c.constraint_id)
    } catch (e) {
      alert(e.message)
      // reload on error
      const res = await getConstraints(session.user_id)
      setConstraints(res.constraints || [])
    }
  }

  const handleEditRule = (c) => {
    const name = ruleName(c)
    navigate('/chat', {
      state: { prefill: `I want to edit my "${name}" spending rule. Current threshold: $${c.threshold_value}.` }
    })
  }

  const handleAddRule = () => {
    navigate('/chat', { state: { prefill: 'I want to add a new spending rule. Help me set one up.' } })
  }

  // ── Danger zone
  const handleExport = async () => {
    try {
      const data = await exportData(session.user_id)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `dragun-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { alert(e.message) }
  }

  const handleDelete = async () => {
    if (!confirm("Delete your account?\n\nYour spending data stays as anonymous records — your name and email are permanently removed. This can't be undone.")) return
    try { await deleteAccount(session.user_id) } catch {}
    logout()
    navigate('/login', { replace: true })
  }

  const SECTIONS = [
    { id: 'account',       label: 'Account' },
    { id: 'profile',       label: 'Profile' },
    { id: 'rules',         label: 'Spending Rules' },
    { id: 'notifications', label: 'Notifications' },
    { id: 'danger',        label: 'Danger Zone', danger: true },
  ]

  return (
    <div className="st-layout">

      {/* ── Left section nav ── */}
      <div className="st-nav">
        <div className="st-nav-label">Jump to</div>
        {SECTIONS.map(s => (
          <button
            key={s.id}
            className={`st-nav-item${activeSection === s.id ? ' active' : ''}${s.danger ? ' danger' : ''}`}
            onClick={() => scrollTo(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* ── Right content ── */}
      <div className="st-content">
        <h1 className="page-title" style={{ marginBottom: 28 }}>Settings</h1>

        {/* ── ACCOUNT ── */}
        <section className="st-section" id="st-account">
          <div className="st-section-label">Account</div>
          <div className="st-field-group">
            <div className="st-field-row">
              <div className="st-field-meta">
                <div className="st-field-label">Email</div>
                <div className="st-field-sub">Used to sign in</div>
              </div>
              <input className="st-field-input" type="email" value={user?.email || session?.email || ''} disabled />
              <span className="st-field-readonly">Read only</span>
            </div>
            <div className="st-field-row">
              <div className="st-field-meta">
                <div className="st-field-label">Handle</div>
                <div className="st-field-sub">Shown in the sidebar</div>
              </div>
              <input
                className="st-field-input"
                type="text"
                value={handle}
                onChange={e => setHandleVal(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSaveHandle() }}
                placeholder="your-handle"
              />
              <div className="st-field-actions">
                {handleMsg && <span className={`st-save-msg${handleMsg.includes('✓') ? ' ok' : ' err'}`}>{handleMsg}</span>}
                <button className="st-save-btn" onClick={handleSaveHandle} disabled={savingHandle}>
                  {savingHandle ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ── PROFILE ── */}
        <section className="st-section" id="st-profile">
          <div className="st-section-label">Profile</div>
          <div className="st-field-group">
            <div className="st-field-row">
              <div className="st-field-meta">
                <div className="st-field-label">Currency</div>
                <div className="st-field-sub">Used across all budgets</div>
              </div>
              <select className="st-field-select" value={currency} onChange={e => setCurrency(e.target.value)}>
                <option value="USD">USD — US Dollar</option>
                <option value="EUR">EUR — Euro</option>
                <option value="GBP">GBP — British Pound</option>
                <option value="INR">INR — Indian Rupee</option>
                <option value="CAD">CAD — Canadian Dollar</option>
              </select>
              <div />
            </div>
            <div className="st-field-row">
              <div className="st-field-meta">
                <div className="st-field-label">Monthly income</div>
                <div className="st-field-sub">Helps Dragun set budgets</div>
              </div>
              <input
                className="st-field-input"
                type="number"
                min="0"
                placeholder="e.g. 4500"
                value={income}
                onChange={e => setIncome(e.target.value)}
              />
              <div />
            </div>
          </div>
          <div className="st-section-footer">
            {profileMsg && <span className={`st-save-msg${profileMsg.includes('✓') ? ' ok' : ' err'}`}>{profileMsg}</span>}
            <button className="st-save-btn" onClick={handleSaveProfile} disabled={savingProfile}>
              {savingProfile ? 'Saving…' : 'Save profile'}
            </button>
          </div>
        </section>

        {/* ── SPENDING RULES ── */}
        <section className="st-section" id="st-rules">
          <div className="st-section-label">
            🛡️ Spending Rules
            <span className="st-section-hint">— set once, run silently. Dragun alerts you in chat when a rule fires.</span>
          </div>

          <div className="st-rules-explainer">
            Rules are real-time guardrails — different from monthly budgets. A rule fires the moment you cross a threshold, then Dragun tells you in chat.
          </div>

          <div className="st-rules-list">
            {constraints.length === 0 ? (
              <div className="st-rules-empty">No spending rules yet. Add one to have Dragun watch your back.</div>
            ) : (
              constraints.map(c => (
                <RuleCard
                  key={c.constraint_id}
                  c={c}
                  onToggle={handleToggleRule}
                  onDelete={handleDeleteRule}
                  onEdit={handleEditRule}
                />
              ))
            )}
          </div>

          <button className="st-add-rule-btn" onClick={handleAddRule}>
            ＋ Add spending rule
          </button>
        </section>

        {/* ── NOTIFICATIONS ── */}
        <section className="st-section" id="st-notifications">
          <div className="st-section-label">Notifications</div>
          <div className="st-notif-group">
            {[
              { key: 'ruleAlerts',     label: 'Spending rule alerts',  sub: 'Get a chat message when a rule fires' },
              { key: 'budgetWarnings', label: 'Budget warnings',       sub: 'Alert when a budget hits 80% used' },
              { key: 'weeklySummary',  label: 'Weekly summary',        sub: 'Dragun sends a recap every Monday morning' },
              { key: 'goalMilestones', label: 'Goal milestones',       sub: 'Celebrate when you hit 25%, 50%, 75% of a goal' },
            ].map(({ key, label, sub }) => (
              <div className="st-notif-item" key={key}>
                <div>
                  <div className="st-notif-label">{label}</div>
                  <div className="st-notif-sub">{sub}</div>
                </div>
                <Toggle
                  checked={notifs[key]}
                  onChange={val => setNotifs(prev => ({ ...prev, [key]: val }))}
                />
              </div>
            ))}
          </div>
        </section>

        {/* ── DANGER ZONE ── */}
        <section className="st-section" id="st-danger">
          <div className="st-section-label st-section-label--danger">Danger Zone</div>
          <div className="st-danger-group">
            <div className="st-danger-row">
              <div>
                <div className="st-danger-label">Export my data</div>
                <div className="st-danger-sub">Download all your transactions, budgets, and goals as JSON</div>
              </div>
              <button className="st-danger-btn" onClick={handleExport}>Export data</button>
            </div>
            <div className="st-danger-row">
              <div>
                <div className="st-danger-label st-danger-label--red">Delete account</div>
                <div className="st-danger-sub">Permanently removes your account and personal data. This cannot be undone.</div>
              </div>
              <button className="st-danger-btn st-danger-btn--red" onClick={handleDelete}>Delete account</button>
            </div>
          </div>
        </section>

        <div style={{ height: 60 }} />
      </div>
    </div>
  )
}
