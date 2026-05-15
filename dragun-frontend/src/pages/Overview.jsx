import { useState, useEffect, useRef } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { getSpendingSummary, getRecentEvents, getBudgets } from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

const DONUT_R    = 58
const DONUT_CIRC = 2 * Math.PI * DONUT_R // ≈ 364.4

function daysLeftInMonth() {
  const now  = new Date()
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return last.getDate() - now.getDate()
}

function monthLabel() {
  return new Date().toLocaleString('en-US', { month: 'long', year: 'numeric' })
}

function relativeTime(isoStr) {
  if (!isoStr) return ''
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 2)  return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs} hr ago`
  if (hrs < 48)  return 'Yesterday'
  return new Date(isoStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const CATEGORY_STYLE = {
  coffee:        { bg: '#fef3e2', color: '#c9922a', emoji: '☕' },
  dining:        { bg: '#eef2fc', color: '#5b8dd9', emoji: '🍽️' },
  restaurants:   { bg: '#eef2fc', color: '#5b8dd9', emoji: '🍽️' },
  transport:     { bg: '#eef2fc', color: '#5b8dd9', emoji: '🚗' },
  groceries:     { bg: '#f0f7f2', color: '#4E9460', emoji: '🛒' },
  entertainment: { bg: '#f3f0fc', color: '#7c5cbf', emoji: '🎮' },
  shopping:      { bg: '#fff0f6', color: '#c4547a', emoji: '🛍️' },
  health:        { bg: '#f0faf5', color: '#2e8b57', emoji: '💊' },
}

function catStyle(cat) {
  return CATEGORY_STYLE[(cat || '').toLowerCase()] || { bg: '#f3f4f6', color: '#6b7280', emoji: '📦' }
}

const QUICK_CHIPS = [
  { emoji: '☕', label: 'Coffee',    category: 'coffee'     },
  { emoji: '🛒', label: 'Groceries', category: 'groceries'  },
  { emoji: '🥗', label: 'Lunch',     category: 'dining'     },
  { emoji: '🚗', label: 'Transport', category: 'transport'  },
  { emoji: '🍽️', label: 'Dining',    category: 'dining'     },
  { emoji: '📦', label: 'Other',     category: 'other'      },
]

// ── Animated donut ────────────────────────────────────────────────────────────

function Donut({ pct }) {
  const fillRef = useRef(null)

  useEffect(() => {
    if (!fillRef.current) return
    const filled = DONUT_CIRC * Math.min(pct / 100, 1)
    const gap    = DONUT_CIRC - filled
    // Small delay so the CSS transition plays after mount
    const t = setTimeout(() => {
      if (fillRef.current) {
        fillRef.current.style.strokeDasharray = `${filled.toFixed(1)} ${gap.toFixed(1)}`
      }
    }, 120)
    return () => clearTimeout(t)
  }, [pct])

  const strokeColor = pct >= 90 ? 'var(--red)' : pct >= 75 ? 'var(--amber)' : 'var(--accent)'

  return (
    <div className="ov-donut-wrap">
      <svg
        className="ov-donut-svg"
        width="148" height="148"
        viewBox="0 0 148 148"
        style={{ transform: 'rotate(-90deg)' }}
      >
        <circle
          cx="74" cy="74" r={DONUT_R}
          fill="none"
          stroke="rgba(107,174,120,.2)"
          strokeWidth="13"
        />
        <circle
          ref={fillRef}
          cx="74" cy="74" r={DONUT_R}
          fill="none"
          stroke={strokeColor}
          strokeWidth="13"
          strokeLinecap="round"
          style={{
            strokeDasharray: '0 364',
            transition: 'stroke-dasharray 1.2s cubic-bezier(.4,0,.2,1)',
          }}
        />
      </svg>
      <div className="ov-donut-center">
        <div className="ov-donut-pct" style={{ color: strokeColor }}>{pct}%</div>
        <div className="ov-donut-label">of budget</div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Overview() {
  const { session }   = useAuth()
  const navigate      = useNavigate()
  const { openChip }  = useOutletContext()

  const [summary,    setSummary]    = useState(null)
  const [budgets,    setBudgets]    = useState([])
  const [events,     setEvents]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [sumRes, budRes, evtRes] = await Promise.allSettled([
          getSpendingSummary(session.user_id, 'month'),
          getBudgets(session.user_id),
          getRecentEvents(session.user_id, 5),
        ])
        if (cancelled) return

        if (sumRes.status === 'fulfilled') setSummary(sumRes.value)
        if (budRes.status === 'fulfilled') setBudgets(budRes.value.budgets || [])
        if (evtRes.status === 'fulfilled') setEvents(evtRes.value.events  || [])
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [session.user_id])

  // ── Derived values ──────────────────────────────────────────────────────
  const totalSpent  = summary?.total_spent ?? 0
  const totalBudget = budgets.reduce((s, b) => s + (b.limit ?? b.amount ?? 0), 0)
  const pct         = totalBudget > 0 ? Math.round((totalSpent / totalBudget) * 100) : 0
  const daysLeft    = daysLeftInMonth()
  const dailyPace   = daysLeft > 0 ? (totalSpent / (new Date().getDate())).toFixed(0) : 0
  const dailyAllow  = totalBudget > 0 ? ((totalBudget - totalSpent) / Math.max(daysLeft, 1)).toFixed(0) : 0

  // Find the most over-budget budget for the suggestion card
  const alertBudget = budgets
    .map(b => ({
      ...b,
      usedPct: b.limit ? Math.round((b.spent / b.limit) * 100) : 0,
    }))
    .sort((a, b) => b.usedPct - a.usedPct)[0]

  // ── Navigate to chat with a pre-filled message ──────────────────────────
  const askAbout = (msg) => navigate('/chat', { state: { prefill: msg } })

  if (loading) {
    return (
      <div className="page">
        <h1 className="page-title">Overview</h1>
        <div className="ov-loading">Loading your snapshot…</div>
      </div>
    )
  }

  return (
    <div className="page">
      <h1 className="page-title">Overview</h1>

      {/* ── Hero card ── */}
      <div className="ov-hero">
        <div className="ov-hero-left">
          <div className="ov-period">This Month · {monthLabel()}</div>
          <div className="ov-amount">${totalSpent.toLocaleString('en-US', { minimumFractionDigits: 0 })}</div>
          {totalBudget > 0 && (
            <div className="ov-of">of ${totalBudget.toLocaleString()} budget</div>
          )}
          <div className="ov-days">{daysLeft} days left in month</div>
          {totalBudget > 0 && (
            <div className="ov-pace">
              Spending&nbsp;
              <span className="ov-pace-warn">~${dailyPace}/day</span>
              &nbsp;· budget allows&nbsp;
              <span className="ov-pace-strong">${dailyAllow}/day</span>
              {Number(dailyPace) > Number(dailyAllow) && (
                <>&nbsp;·&nbsp;<span className="ov-pace-warn">watch spending 🔥</span></>
              )}
            </div>
          )}
        </div>
        <Donut pct={pct} />
      </div>

      {/* ── Contextual Ask Dragun card ── */}
      {alertBudget && alertBudget.usedPct >= 80 && (
        <button
          className="ov-suggest"
          onClick={() => askAbout(
            `I've used ${alertBudget.usedPct}% of my ${alertBudget.category} budget with ${daysLeft} days left. How should I pace the rest of the month?`
          )}
        >
          <span className="ov-suggest-icon">💬</span>
          <span className="ov-suggest-text">
            You've used <strong>{alertBudget.usedPct}%</strong> of your{' '}
            {alertBudget.category} budget with {daysLeft} days left —{' '}
            ask Dragun how to pace the rest of the month
          </span>
          <span className="ov-suggest-arrow">→</span>
        </button>
      )}

      {/* ── Quick-log chips ── */}
      <div className="section-label" style={{ marginTop: 26 }}>Log Quickly</div>
      <div className="chips">
        {QUICK_CHIPS.map(({ emoji, label, category }) => (
          <button
            key={label}
            className="log-chip"
            onClick={() => openChip(category)}
          >
            <span className="log-chip-emoji">{emoji}</span> {label}
          </button>
        ))}
      </div>

      {/* ── Recent activity ── */}
      <div className="section-label" style={{ marginTop: 26 }}>Recent</div>

      {events.length === 0 ? (
        <div className="ov-empty">
          No activity yet — log a purchase to get started.
        </div>
      ) : (
        <div className="activity-list">
          {events.map((evt) => {
            const merchant = evt.item_description || evt.item_normalized || 'Purchase'
            const amount   = evt.total_cost ?? evt.unit_cost ?? 0
            const cat      = (evt.tags?.[0] || '').toLowerCase()
            const style    = catStyle(cat)

            return (
              <div className="activity-item" key={evt.event_id}>
                <div className="act-icon" style={{ background: style.bg }}>
                  {style.emoji}
                </div>
                <div className="act-body">
                  <div className="act-merchant">{merchant}</div>
                  <div className="act-meta">{relativeTime(evt.event_timestamp)}</div>
                </div>
                {cat && (
                  <span
                    className="act-badge"
                    style={{ background: style.bg, color: style.color }}
                  >
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </span>
                )}
                <div className="act-amount">
                  −${Number(amount).toFixed(2)}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {error && <p className="ov-error">{error}</p>}

      <div style={{ height: 28 }} />
    </div>
  )
}
