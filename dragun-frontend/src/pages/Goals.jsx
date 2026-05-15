import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { getGoals, createGoal, updateGoal, deleteGoal } from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

const GOAL_EMOJI = {
  vacation:   '🏖️', beach: '🏖️', travel: '✈️', trip: '✈️',
  car:        '🚗', tires: '🚗', auto: '🚗', vehicle: '🚗',
  house:      '🏠', home: '🏠', rent: '🏠',
  phone:      '📱', laptop: '💻', computer: '💻', tech: '💻',
  emergency:  '🛡️', fund: '💰', savings: '💰',
  wedding:    '💍', ring: '💍',
  baby:       '👶',
  fitness:    '🏋️', gym: '🏋️',
  education:  '📚', school: '📚', tuition: '🎓',
  gift:       '🎁', holiday: '🎁',
}

function goalEmoji(name, category) {
  const src = (name + ' ' + (category || '')).toLowerCase()
  for (const [key, emoji] of Object.entries(GOAL_EMOJI)) {
    if (src.includes(key)) return emoji
  }
  return '🎯'
}

function fmt$(n) {
  return '$' + Number(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  })
}

function monthsAgo(isoDate) {
  if (!isoDate) return 1
  const ms = Date.now() - new Date(isoDate).getTime()
  return Math.max(ms / (1000 * 60 * 60 * 24 * 30), 0.5)
}

function daysUntil(isoDate) {
  if (!isoDate) return null
  const ms = new Date(isoDate + 'T00:00:00').getTime() - Date.now()
  return Math.ceil(ms / (1000 * 60 * 60 * 24))
}

function goalStats(g) {
  const pct        = g.target_amount > 0 ? g.current_amount / g.target_amount : 0
  const remaining  = Math.max(g.target_amount - g.current_amount, 0)
  const monthsOld  = monthsAgo(g.created_at)
  const monthlyRate = g.current_amount > 0 ? g.current_amount / monthsOld : 0
  const monthsToGo = monthlyRate > 0 ? remaining / monthlyRate : null

  let paceLabel = 'On pace'
  let paceStyle = 'amber'
  if (g.deadline) {
    const daysLeft   = daysUntil(g.deadline)
    const monthsLeft = (daysLeft || 0) / 30
    if (monthlyRate > 0 && monthsToGo !== null) {
      if (monthsToGo < monthsLeft * 0.85)      { paceLabel = '⚡ Ahead of pace'; paceStyle = 'green' }
      else if (monthsToGo > monthsLeft * 1.15) { paceLabel = '⚠️ Behind pace';  paceStyle = 'red'   }
    }
  } else if (monthlyRate > 0) {
    paceLabel = '⚡ Ahead of pace'; paceStyle = 'green'
  }

  return { pct, remaining, monthlyRate, monthsToGo, paceLabel, paceStyle }
}

const PACE_STYLE = {
  green: { background: 'var(--accent-light)', color: 'var(--accent-dim)' },
  amber: { background: 'var(--amber-light)',  color: 'var(--amber)'     },
  red:   { background: '#fdf2f2',             color: 'var(--red)'       },
}

// ── Goal card ─────────────────────────────────────────────────────────────────

function GoalCard({ g, onContribute, onEdit, onDelete, onAsk }) {
  const { pct, monthlyRate, monthsToGo, paceLabel, paceStyle } = goalStats(g)
  const pctPx   = Math.min(Math.round(pct * 100), 100)
  const emoji   = goalEmoji(g.name, g.category)
  const fillRef = useRef(null)

  useEffect(() => {
    const t = setTimeout(() => {
      if (fillRef.current) fillRef.current.style.width = `${pctPx}%`
    }, 120)
    return () => clearTimeout(t)
  }, [pctPx])

  const deadlineLabel = g.deadline
    ? `Target: ${new Date(g.deadline + 'T00:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}`
    : 'No deadline set'

  const timeLabel = pctPx >= 100
    ? '🎉 Goal reached!'
    : monthsToGo !== null && monthsToGo > 0
      ? `~${Math.ceil(monthsToGo)} month${Math.ceil(monthsToGo) !== 1 ? 's' : ''} at current pace · contributing ~${fmt$(monthlyRate)}/month`
      : monthlyRate === 0
        ? 'Start contributing to see your pace'
        : 'Almost there!'

  return (
    <div className="gl-card">
      <div className="gl-stripe" />
      <div className="gl-body">

        <div className="gl-actions">
          <button className="gl-action-btn" onClick={() => onEdit(g)}>Edit</button>
          <button className="gl-action-btn del" onClick={() => onDelete(g)}>Delete</button>
        </div>

        <div className="gl-top">
          <div className="gl-icon-wrap">{emoji}</div>
          <div className="gl-info">
            <div className="gl-name">
              {g.name}
              <span className="gl-pace-badge" style={PACE_STYLE[paceStyle]}>{paceLabel}</span>
            </div>
            <div className="gl-meta">{fmt$(g.target_amount)} goal &nbsp;·&nbsp; {deadlineLabel}</div>
            <div className="gl-time">{timeLabel}</div>
          </div>
          <div className="gl-pct-badge">
            <div className="gl-pct-num">{pctPx}%</div>
            <div className="gl-pct-lbl">saved</div>
          </div>
        </div>

        {/* Progress bar with milestone ticks */}
        <div className="gl-bar-wrap">
          <div className="gl-track">
            <div className="gl-fill" ref={fillRef} style={{ width: '0%' }} />
            <div className="gl-milestone" style={{ left: '25%' }} />
            <div className="gl-milestone" style={{ left: '50%' }} />
            <div className="gl-milestone" style={{ left: '75%' }} />
            <div className="gl-flag-end">{pctPx >= 100 ? '🏆' : '🏁'}</div>
          </div>
          <div className="gl-bar-labels">
            <span className="gl-saved-lbl">{fmt$(g.current_amount)} saved</span>
            <span>25%</span>
            <span>50%</span>
            <span>75%</span>
            <span className="gl-target-lbl">{fmt$(g.target_amount)}</span>
          </div>
        </div>

        <div className="gl-footer">
          <button className="gl-contribute-btn" onClick={() => onContribute(g)}>
            ＋ Contribute
          </button>
          <button className="gl-ask-link" onClick={() => onAsk(g)}>
            💬 Ask Dragun how to reach this faster →
          </button>
        </div>

      </div>
    </div>
  )
}

// ── New / Edit goal modal ─────────────────────────────────────────────────────

function GoalModal({ initial, onSave, onClose }) {
  const isEdit   = !!initial
  const [name,     setName]     = useState(initial?.name || '')
  const [amount,   setAmount]   = useState(initial?.target_amount ?? '')
  const [deadline, setDeadline] = useState(initial?.deadline || '')
  const [saving,   setSaving]   = useState(false)
  const [err,      setErr]      = useState('')
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSave = async () => {
    if (!name.trim())            { setErr('Goal name is required'); return }
    if (!amount || amount <= 0)  { setErr('Enter a valid target amount'); return }
    setSaving(true); setErr('')
    try {
      await onSave({ name: name.trim(), target_amount: parseFloat(amount), deadline: deadline || null })
    } catch (e) {
      setErr(e.message); setSaving(false)
    }
  }

  return (
    <div className="bgt-modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bgt-modal">
        <div className="bgt-modal-title">{isEdit ? 'Edit goal' : 'New goal'}</div>

        <div className="bgt-modal-field">
          <label>Goal name</label>
          <input ref={inputRef} type="text" placeholder="e.g. Beach Vacation, New Laptop…"
            value={name} onChange={e => setName(e.target.value)} disabled={isEdit} />
        </div>

        <div className="bgt-modal-field">
          <label>Target amount</label>
          <input type="number" placeholder="1000" min="1"
            value={amount} onChange={e => setAmount(e.target.value)} />
        </div>

        <div className="bgt-modal-field">
          <label>Deadline (optional)</label>
          <input type="date" value={deadline} onChange={e => setDeadline(e.target.value)} />
        </div>

        {err && <div className="bgt-modal-err">{err}</div>}
        <div className="bgt-modal-actions">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create goal'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Contribute modal ──────────────────────────────────────────────────────────

function ContributeModal({ goal, onSave, onClose }) {
  const [amount, setAmount] = useState('')
  const [saving, setSaving] = useState(false)
  const [err,    setErr]    = useState('')
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSave = async () => {
    if (!amount || parseFloat(amount) <= 0) { setErr('Enter a valid amount'); return }
    setSaving(true); setErr('')
    try {
      await onSave(goal, parseFloat(amount))
    } catch (e) {
      setErr(e.message); setSaving(false)
    }
  }

  const remaining = Math.max(goal.target_amount - goal.current_amount, 0)

  return (
    <div className="bgt-modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bgt-modal">
        <div className="bgt-modal-title">Contribute to {goal.name}</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 18 }}>
          {fmt$(goal.current_amount)} saved · {fmt$(remaining)} to go
        </div>

        <div className="bgt-modal-field">
          <label>Amount to add</label>
          <input ref={inputRef} type="number" placeholder="50" min="0.01" step="0.01"
            value={amount} onChange={e => setAmount(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSave() }} />
        </div>

        {err && <div className="bgt-modal-err">{err}</div>}
        <div className="bgt-modal-actions">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : '＋ Add to goal'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Goals() {
  const { session } = useAuth()
  const navigate    = useNavigate()
  const [goals,   setGoals]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [modal,   setModal]   = useState(null) // null | 'new' | { goal } | { contribute }

  const load = async () => {
    try {
      const res = await getGoals(session.user_id)
      setGoals((res.goals || []).filter(g => g.status === 'active'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [session.user_id])

  const handleCreate = async (fields) => {
    await createGoal(session.user_id, fields)
    setModal(null); setLoading(true); await load()
  }

  const handleEdit = async (fields) => {
    await updateGoal(session.user_id, modal.goal.goal_id, {
      target_amount: fields.target_amount,
      deadline:      fields.deadline,
    })
    setModal(null); setLoading(true); await load()
  }

  const handleContribute = async (goal, amount) => {
    await updateGoal(session.user_id, goal.goal_id, {
      current_amount: goal.current_amount + amount,
    })
    setModal(null); setLoading(true); await load()
  }

  const handleDelete = async (g) => {
    if (!confirm(`Delete your "${g.name}" goal?`)) return
    try {
      await deleteGoal(session.user_id, g.goal_id)
      setGoals(prev => prev.filter(x => x.goal_id !== g.goal_id))
    } catch (e) {
      alert(e.message)
    }
  }

  const askAbout = (g) => {
    const { pct } = goalStats(g)
    navigate('/chat', {
      state: {
        prefill: `I'm saving for "${g.name}" — ${fmt$(g.current_amount)} saved of ${fmt$(g.target_amount)} (${Math.round(pct * 100)}%)${g.deadline ? `, deadline ${g.deadline}` : ''}. How can I reach this goal faster?`,
      }
    })
  }

  const totalSaved = goals.reduce((s, g) => s + g.current_amount, 0)
  const aheadCount = goals.filter(g => goalStats(g).paceStyle === 'green').length

  const encouragement = (() => {
    if (goals.length === 0) return null
    if (aheadCount > 0) return { emoji: '🔥', text: `You've saved ${fmt$(totalSaved)} across ${goals.length} goal${goals.length !== 1 ? 's' : ''} — keep that momentum going!` }
    if (totalSaved > 0) return { emoji: '💪', text: `${fmt$(totalSaved)} saved so far — every contribution counts. You're building something real.` }
    return { emoji: '🌱', text: 'Ready to start saving? Hit Contribute on any goal and watch your progress grow.' }
  })()

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="gl-page-header">
        <div>
          <div className="gl-title-group">
            <h1 className="page-title">Goals</h1>
            <span className="gl-extra-badge">✦ Extra credit</span>
          </div>
          <div className="gl-page-sub">
            Saving for something great? This is where it happens — totally optional, but very satisfying.
          </div>
        </div>
        <button className="bgt-header-btn" onClick={() => setModal('new')}>＋ New goal</button>
      </div>

      {loading ? (
        <div className="bgt-loading">Loading goals…</div>
      ) : error ? (
        <div className="bgt-error">{error}</div>
      ) : (
        <>
          {encouragement && goals.length > 0 && (
            <div className="gl-encourage">
              <div className="gl-encourage-emoji">{encouragement.emoji}</div>
              <div className="gl-encourage-text">{encouragement.text}</div>
            </div>
          )}

          {goals.length > 0 && (
            <div className="gl-summary-row">
              <div className="gl-summary-pill">🎯 <strong>{goals.length}</strong> active {goals.length === 1 ? 'goal' : 'goals'}</div>
              <span className="gl-summary-sep">·</span>
              <div className="gl-summary-pill">💰 <strong>{fmt$(totalSaved)}</strong> saved total</div>
              {aheadCount > 0 && (
                <>
                  <span className="gl-summary-sep">·</span>
                  <div className="gl-summary-pill">⚡ <strong>{aheadCount}</strong> ahead of pace</div>
                </>
              )}
            </div>
          )}

          {goals.length === 0 ? (
            <div className="bgt-empty">
              No goals yet.{' '}
              <button className="bgt-empty-link" onClick={() => setModal('new')}>
                Create your first goal →
              </button>
            </div>
          ) : (
            goals.map(g => (
              <GoalCard
                key={g.goal_id}
                g={g}
                onContribute={(g) => setModal({ contribute: g })}
                onEdit={(g) => setModal({ goal: g })}
                onDelete={handleDelete}
                onAsk={askAbout}
              />
            ))
          )}

          <button className="gl-add-card" onClick={() => setModal('new')}>
            <div className="gl-add-icon">＋</div>
            <div className="gl-add-label">New goal</div>
            <div className="gl-add-sub">saving for something? tell Dragun and it'll help you plan</div>
          </button>
        </>
      )}

      {modal === 'new' && <GoalModal onSave={handleCreate} onClose={() => setModal(null)} />}
      {modal?.goal && <GoalModal initial={modal.goal} onSave={handleEdit} onClose={() => setModal(null)} />}
      {modal?.contribute && <ContributeModal goal={modal.contribute} onSave={handleContribute} onClose={() => setModal(null)} />}
    </div>
  )
}
