import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { getBudgets, createBudget, updateBudget, deleteBudget } from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

const SCOPE_EMOJI = {
  groceries:     '🛒', grocery: '🛒',
  dining:        '🍽️', restaurants: '🍽️',
  coffee:        '☕',
  transport:     '🚗', transportation: '🚗',
  entertainment: '🎮',
  shopping:      '🛍️',
  health:        '💊',
  all:           '💰',
}
const scopeEmoji = (s) => SCOPE_EMOJI[(s || '').toLowerCase()] || '📦'

function statusOf(pct) {
  if (pct >= 1.0)  return 'red'
  if (pct >= 0.85) return 'amber'
  return 'green'
}

function judgment(pct) {
  if (pct >= 1.0)  return 'Over budget 🚨'
  if (pct >= 0.9)  return 'Cutting it close 🔥'
  if (pct >= 0.8)  return 'Almost there ⚠️'
  return 'On track ✓'
}

const STATUS_COLOR = {
  red:   'var(--red)',
  amber: 'var(--amber)',
  green: 'var(--accent-dim)',
}

const STATUS_BG = {
  red:   'var(--red-light, #fdf2f2)',
  amber: 'var(--surface)',
  green: 'var(--surface)',
}

function fmt$(n) {
  return '$' + Number(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: 0, maximumFractionDigits: 2,
  })
}

// ── Budget card ───────────────────────────────────────────────────────────────

function BudgetCard({ b, onEdit, onDelete }) {
  const pct    = b.pct_consumed ?? 0
  const status = statusOf(pct)
  const color  = STATUS_COLOR[status]
  const pctPx  = Math.min(Math.round(pct * 100), 100)
  const overBy = pct >= 1 ? b.amount_spent - b.budget_amount : 0
  const label  = (b.budget_scope || 'Budget').charAt(0).toUpperCase() + (b.budget_scope || '').slice(1)

  return (
    <div className="bgt-card" style={{ background: STATUS_BG[status] }}>
      {/* Status top border */}
      <div className="bgt-card-bar" style={{ background: color }} />

      <div className="bgt-card-body">
        {/* Hover actions */}
        <div className="bgt-actions">
          <button className="bgt-action-btn" onClick={() => onEdit(b)}>Edit</button>
          <button className="bgt-action-btn del" onClick={() => onDelete(b)}>Delete</button>
        </div>

        {/* Title row */}
        <div className="bgt-title-row">
          <div className="bgt-title">
            <span className="bgt-title-emoji">{scopeEmoji(b.budget_scope)}</span>
            {label}
          </div>
          <div className="bgt-period">{b.period_type === 'weekly' ? 'Week' : 'Month'}</div>
        </div>

        {/* Hero */}
        <div className="bgt-hero">
          <span className="bgt-spent" style={{ color }}>{fmt$(b.amount_spent)}</span>
          <span className="bgt-of">of {fmt$(b.budget_amount)}</span>
        </div>
        <div className="bgt-budget-lbl">
          {b.period_type === 'weekly' ? 'weekly' : 'monthly'} budget
        </div>

        {/* Progress bar */}
        <div className="bgt-track" style={{ background: status === 'red' ? '#f5c2c2' : undefined }}>
          <div
            className="bgt-fill"
            style={{ width: `${pctPx}%`, background: color }}
          />
          {pct >= 1 && <div className="bgt-overflow-flag">!</div>}
        </div>

        {/* Meta */}
        <div className="bgt-meta">
          {pct >= 1
            ? <><strong style={{ color: 'var(--red)' }}>Over by {fmt$(overBy)}</strong> · {b.days_remaining} days left</>
            : <>{Math.round(pct * 100)}% used · {b.days_remaining} days left · ~{fmt$(b.daily_pace)}/day remaining</>
          }
        </div>

        {/* Judgment */}
        <div className="bgt-judgment" style={{ color }}>{judgment(pct)}</div>
      </div>
    </div>
  )
}

// ── New / Edit budget modal ───────────────────────────────────────────────────

function BudgetModal({ initial, onSave, onClose }) {
  const isEdit = !!initial
  const [scope,    setScope]    = useState(initial?.budget_scope || '')
  const [amount,   setAmount]   = useState(initial?.budget_amount ?? '')
  const [period,   setPeriod]   = useState(initial?.period_type  || 'monthly')
  const [saving,   setSaving]   = useState(false)
  const [err,      setErr]      = useState('')
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const handleSave = async () => {
    if (!scope.trim())       { setErr('Category is required'); return }
    if (!amount || amount <= 0) { setErr('Enter a valid amount'); return }
    setSaving(true)
    setErr('')
    try {
      await onSave({ budget_scope: scope.trim(), budget_amount: parseFloat(amount), period_type: period })
    } catch (e) {
      setErr(e.message)
      setSaving(false)
    }
  }

  return (
    <div className="bgt-modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bgt-modal">
        <div className="bgt-modal-title">{isEdit ? 'Edit budget' : 'New budget'}</div>

        <div className="bgt-modal-field">
          <label>Category</label>
          <input
            ref={inputRef}
            type="text"
            placeholder="e.g. groceries, dining, coffee…"
            value={scope}
            onChange={e => setScope(e.target.value)}
            disabled={isEdit}
          />
        </div>

        <div className="bgt-modal-field">
          <label>Budget amount</label>
          <input
            type="number"
            placeholder="200"
            min="1"
            value={amount}
            onChange={e => setAmount(e.target.value)}
          />
        </div>

        <div className="bgt-modal-field">
          <label>Period</label>
          <div className="bgt-period-toggle">
            <button
              className={`bgt-period-btn${period === 'monthly' ? ' active' : ''}`}
              onClick={() => setPeriod('monthly')}
            >Monthly</button>
            <button
              className={`bgt-period-btn${period === 'weekly' ? ' active' : ''}`}
              onClick={() => setPeriod('weekly')}
            >Weekly</button>
          </div>
        </div>

        {err && <div className="bgt-modal-err">{err}</div>}

        <div className="bgt-modal-actions">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create budget'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Budgets() {
  const { session }  = useAuth()
  const navigate     = useNavigate()
  const [budgets,  setBudgets]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [modal,    setModal]    = useState(null) // null | 'new' | { budget }

  const load = async () => {
    try {
      const res = await getBudgets(session.user_id)
      setBudgets((res.budgets || []).sort((a, b) => (b.pct_consumed ?? 0) - (a.pct_consumed ?? 0)))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [session.user_id])

  // ── Actions ───────────────────────────────────────────────────────────────
  const handleCreate = async (fields) => {
    await createBudget(session.user_id, {
      budget_scope:  fields.budget_scope,
      scope_tags:    [fields.budget_scope],
      budget_amount: fields.budget_amount,
      period_type:   fields.period_type,
    })
    setModal(null)
    setLoading(true)
    await load()
  }

  const handleEdit = async (fields) => {
    await updateBudget(session.user_id, modal.budget.budget_id, {
      budget_amount: fields.budget_amount,
      period_type:   fields.period_type,
    })
    setModal(null)
    setLoading(true)
    await load()
  }

  const handleDelete = async (b) => {
    if (!confirm(`Delete your ${b.budget_scope} budget?`)) return
    try {
      await deleteBudget(session.user_id, b.budget_id)
      setBudgets(prev => prev.filter(x => x.budget_id !== b.budget_id))
    } catch (e) {
      alert(e.message)
    }
  }

  const askAbout = (msg) => navigate('/chat', { state: { prefill: msg } })

  // ── Summary counts ────────────────────────────────────────────────────────
  const onTrack     = budgets.filter(b => (b.pct_consumed ?? 0) < 0.8).length
  const approaching = budgets.filter(b => { const p = b.pct_consumed ?? 0; return p >= 0.8 && p < 1 }).length
  const over        = budgets.filter(b => (b.pct_consumed ?? 0) >= 1).length
  const overBudgets = budgets.filter(b => (b.pct_consumed ?? 0) >= 1)

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="bgt-page-header">
        <h1 className="page-title">Budgets</h1>
        <button className="bgt-header-btn" onClick={() => setModal('new')}>
          ＋ New budget
        </button>
      </div>

      {loading ? (
        <div className="bgt-loading">Loading budgets…</div>
      ) : error ? (
        <div className="bgt-error">{error}</div>
      ) : (
        <>
          {/* ── Summary bar ── */}
          {budgets.length > 0 && (
            <div className="bgt-summary-bar">
              <div className="bgt-summary-item">
                <div className="bgt-summary-dot" style={{ background: 'var(--accent)' }} />
                <span><span className="bgt-summary-val">{onTrack}</span> on track</span>
              </div>
              {approaching > 0 && (
                <>
                  <div className="bgt-summary-divider" />
                  <div className="bgt-summary-item">
                    <div className="bgt-summary-dot" style={{ background: 'var(--amber)' }} />
                    <span><span className="bgt-summary-val">{approaching}</span> approaching limit</span>
                  </div>
                </>
              )}
              {over > 0 && (
                <>
                  <div className="bgt-summary-divider" />
                  <div className="bgt-summary-item">
                    <div className="bgt-summary-dot" style={{ background: 'var(--red)' }} />
                    <span><span className="bgt-summary-val">{over}</span> over budget</span>
                  </div>
                </>
              )}
              <div className="bgt-summary-right">
                {new Date().toLocaleString('en-US', { month: 'long', year: 'numeric' })}
                {budgets[0]?.days_remaining != null &&
                  ` · ${budgets[0].days_remaining} days remaining`}
              </div>
            </div>
          )}

          {/* ── Card grid ── */}
          {budgets.length === 0 ? (
            <div className="bgt-empty">
              No budgets yet.{' '}
              <button className="bgt-empty-link" onClick={() => setModal('new')}>
                Create your first budget →
              </button>
            </div>
          ) : (
            <div className="bgt-card-grid">
              {budgets.map((b, i) => (
                <>
                  <BudgetCard
                    key={b.budget_id}
                    b={b}
                    onEdit={(b) => setModal({ budget: b })}
                    onDelete={handleDelete}
                  />
                  {/* Ask Dragun strip after the first over-budget card */}
                  {(b.pct_consumed ?? 0) >= 1 && (
                    <div
                      key={`strip-${b.budget_id}`}
                      className="bgt-ask-strip bgt-grid-full"
                      onClick={() => askAbout(
                        `My ${b.budget_scope} budget is over by ${fmt$(b.amount_spent - b.budget_amount)} with ${b.days_remaining} days left. Should I adjust the budget or find ways to cut spending?`
                      )}
                    >
                      <span className="bgt-ask-icon">💬</span>
                      <span className="bgt-ask-text">
                        Your {b.budget_scope} budget is{' '}
                        <strong>over by {fmt$(b.amount_spent - b.budget_amount)}</strong>{' '}
                        with {b.days_remaining} days left — ask Dragun to adjust it or find where to cut
                      </span>
                      <span className="bgt-ask-arrow">→</span>
                    </div>
                  )}
                </>
              ))}

              {/* Add budget card */}
              <button className="bgt-add-card" onClick={() => setModal('new')}>
                <div className="bgt-add-icon">＋</div>
                <div className="bgt-add-label">New budget</div>
                <div className="bgt-add-sub">or ask Dragun to set one up</div>
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Modals ── */}
      {modal === 'new' && (
        <BudgetModal onSave={handleCreate} onClose={() => setModal(null)} />
      )}
      {modal?.budget && (
        <BudgetModal
          initial={modal.budget}
          onSave={handleEdit}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  )
}
