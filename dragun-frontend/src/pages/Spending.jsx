import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { getSpendingSummary, getSpendingDaily, getRecentEvents } from '../api.js'

// ── Constants ─────────────────────────────────────────────────────────────────

const PERIODS = [
  { label: 'This month', value: 'month' },
  { label: 'This week',  value: 'week'  },
]

const CAT_CONFIG = {
  dining:        { color: '#5b8dd9', bg: '#eef2fc', emoji: '🍽️' },
  restaurants:   { color: '#5b8dd9', bg: '#eef2fc', emoji: '🍽️' },
  groceries:     { color: '#6BAE78', bg: '#f0f7f2', emoji: '🛒' },
  coffee:        { color: '#c9922a', bg: '#fef3e2', emoji: '☕' },
  entertainment: { color: '#9b8dd9', bg: '#f3f0fc', emoji: '🎮' },
  transport:     { color: '#5b8dd9', bg: '#eef2fc', emoji: '🚗' },
  shopping:      { color: '#c4547a', bg: '#fff0f6', emoji: '🛍️' },
  health:        { color: '#2e8b57', bg: '#f0faf5', emoji: '💊' },
  uncategorized: { color: '#9ca3af', bg: '#f3f4f6', emoji: '📦' },
}

function catCfg(cat) {
  return CAT_CONFIG[(cat || '').toLowerCase()] || CAT_CONFIG.uncategorized
}

function fmt$(n) {
  return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtDate(isoDate) {
  if (!isoDate) return ''
  const d = new Date(isoDate + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Bar chart ─────────────────────────────────────────────────────────────────

function SpendingChart({ days, eventsByDate }) {
  const [tooltip, setTooltip] = useState(null) // { x, y, text }
  const chartRef = useRef(null)

  if (!days || days.length === 0) {
    return <div className="sp-chart-empty">No data for this period</div>
  }

  const maxVal   = Math.max(...days.map(d => d.amount), 1)
  const today    = new Date().toISOString().slice(0, 10)

  // X-axis labels: first, ~quarter, mid, ~three-quarter, last
  const labelIdxs = [0, Math.floor(days.length * 0.25), Math.floor(days.length * 0.5),
                     Math.floor(days.length * 0.75), days.length - 1]

  return (
    <div className="sp-chart-wrap" ref={chartRef}>
      <div className="sp-chart-area">
        {days.map((day) => {
          const isToday  = day.date === today
          const isFuture = day.date > today
          const domCat   = eventsByDate[day.date]?.dominantCat || 'uncategorized'
          const color    = isFuture ? '#e9e9e9' : isToday ? '#6BAE78' : catCfg(domCat).color
          const heightPct = isFuture ? 1.5 : Math.max((day.amount / maxVal) * 100, day.amount > 0 ? 2 : 1.5)

          return (
            <div
              key={day.date}
              className="sp-bar-col"
              onMouseEnter={(e) => {
                if (isFuture || day.amount === 0) return
                const rect = e.currentTarget.getBoundingClientRect()
                const tipLines = [
                  fmtDate(day.date) + (isToday ? ' (today)' : ''),
                  fmt$(day.amount),
                ]
                if (eventsByDate[day.date]?.topMerchants) {
                  tipLines.push(...eventsByDate[day.date].topMerchants.slice(0, 2))
                }
                setTooltip({ x: rect.left + rect.width / 2, y: rect.top - 10, text: tipLines })
              }}
              onMouseLeave={() => setTooltip(null)}
            >
              <div
                className="sp-bar"
                style={{
                  height: `${heightPct}%`,
                  background: color,
                  borderRadius: isToday ? '4px 4px 0 0' : undefined,
                  boxShadow: isToday ? '0 0 0 2px rgba(107,174,120,.35)' : undefined,
                }}
              />
            </div>
          )
        })}
      </div>

      {/* X axis */}
      <div className="sp-chart-x">
        {labelIdxs.map(i => {
          const d = days[i]
          const isToday = d?.date === today
          return (
            <span key={i} className={`sp-chart-x-lbl${isToday ? ' sp-today-lbl' : ''}`}>
              {d ? fmtDate(d.date) : ''}
              {isToday ? ' ▾' : ''}
            </span>
          )
        })}
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="sp-tip"
          style={{ left: tooltip.x, top: tooltip.y, transform: 'translate(-50%, -100%)' }}
        >
          {tooltip.text.map((t, i) => <div key={i}>{t}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Category leaderboard row ──────────────────────────────────────────────────

function CatRow({ cat, amount, pct, rank, maxAmount, events, onAsk }) {
  const [open, setOpen] = useState(false)
  const cfg      = catCfg(cat)
  const barWidth = maxAmount > 0 ? (amount / maxAmount) * 100 : 0
  const catEvents = events.filter(e => (e.tags?.[0] || '').toLowerCase() === cat.toLowerCase())
  const label    = cat.charAt(0).toUpperCase() + cat.slice(1)

  return (
    <>
      <div
        className={`sp-cat-row${open ? ' open' : ''}`}
        onClick={() => setOpen(v => !v)}
      >
        <div className="sp-cat-rank">#{rank}</div>
        <div className="sp-cat-icon" style={{ background: cfg.bg }}>{cfg.emoji}</div>
        <div className="sp-cat-body">
          <div className="sp-cat-name">{label}</div>
          <div className="sp-cat-bar-track">
            <div className="sp-cat-bar-fill" style={{ width: `${barWidth}%`, background: cfg.color }} />
          </div>
        </div>
        <div className="sp-cat-amounts">
          <div className="sp-cat-amount">{fmt$(amount)}</div>
          <div className="sp-cat-pct">{pct}% of total</div>
        </div>
        <div className="sp-cat-chevron">{open ? '▴' : '▾'}</div>
      </div>

      {open && (
        <div className="sp-drawer">
          <div className="sp-drawer-inner">
            {catEvents.length === 0 ? (
              <div className="sp-drawer-empty">No individual transactions found.</div>
            ) : (
              catEvents.slice(0, 10).map((evt) => (
                <div className="sp-txn-row" key={evt.event_id}>
                  <span className="sp-txn-merchant">
                    {evt.item_description || evt.item_normalized || 'Purchase'}
                  </span>
                  <span className="sp-txn-date">
                    {evt.event_timestamp
                      ? fmtDate(evt.event_timestamp.slice(0, 10))
                      : ''}
                  </span>
                  <span className="sp-txn-amount">−{fmt$(evt.total_cost ?? 0)}</span>
                </div>
              ))
            )}
            <button
              className="sp-drawer-ask"
              onClick={(e) => { e.stopPropagation(); onAsk(label) }}
            >
              💬 Ask Dragun about {label.toLowerCase()} →
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Spending() {
  const { session }  = useAuth()
  const navigate     = useNavigate()
  const [period, setPeriod]     = useState('month')
  const [summary, setSummary]   = useState(null)
  const [dailyData, setDailyData] = useState([])
  const [events, setEvents]     = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      try {
        const [sumRes, dailyRes, evtRes] = await Promise.allSettled([
          getSpendingSummary(session.user_id, period),
          getSpendingDaily(session.user_id, period),
          getRecentEvents(session.user_id, 100),
        ])
        if (cancelled) return
        if (sumRes.status   === 'fulfilled') setSummary(sumRes.value)
        if (dailyRes.status === 'fulfilled') setDailyData(dailyRes.value.days || [])
        if (evtRes.status   === 'fulfilled') setEvents(evtRes.value.events || [])
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [session.user_id, period])

  // ── Derived: map events by date for bar coloring ──────────────────────────
  const eventsByDate = {}
  events.forEach(evt => {
    const d = evt.event_timestamp?.slice(0, 10)
    if (!d) return
    if (!eventsByDate[d]) eventsByDate[d] = { cats: {}, topMerchants: [] }
    const cat = (evt.tags?.[0] || 'uncategorized').toLowerCase()
    eventsByDate[d].cats[cat] = (eventsByDate[d].cats[cat] || 0) + (evt.total_cost || 0)
    if (evt.item_description) eventsByDate[d].topMerchants.push(evt.item_description)
  })
  Object.values(eventsByDate).forEach(d => {
    d.dominantCat = Object.entries(d.cats).sort((a, b) => b[1] - a[1])[0]?.[0] || 'uncategorized'
  })

  // ── Derived: spending stats ───────────────────────────────────────────────
  const totalSpent  = summary?.total_spent ?? 0
  const categories  = (summary?.by_category || []).sort((a, b) => b.amount - a.amount)
  const maxCatAmt   = categories[0]?.amount || 1
  const topCat      = categories[0]

  // Find biggest mover for the inline prompt
  const askAbout = useCallback((msg) => {
    navigate('/chat', { state: { prefill: msg } })
  }, [navigate])

  // Active category colors for the key
  const activeCats = [...new Set(categories.map(c => c.category.toLowerCase()))].slice(0, 6)

  return (
    <div className="page">
      {/* ── Page header with period toggle ── */}
      <div className="sp-page-header">
        <h1 className="page-title">Spending</h1>
        <div className="sp-period-toggle">
          {PERIODS.map(p => (
            <button
              key={p.value}
              className={`sp-period-btn${period === p.value ? ' active' : ''}`}
              onClick={() => setPeriod(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="sp-loading">Loading spending data…</div>
      ) : error ? (
        <div className="sp-error">{error}</div>
      ) : (
        <>
          {/* ── Chart hero card ── */}
          <div className="sp-chart-hero">
            {/* Pulse summary row */}
            <div className="sp-pulse-row">
              <div className="sp-pulse-left">
                <div className="sp-pulse-eyebrow">
                  Total spent · {period === 'week' ? 'This week' : new Date().toLocaleString('en-US', { month: 'long', year: 'numeric' })}
                </div>
                <div className="sp-pulse-main">
                  <div className="sp-pulse-amount">{fmt$(totalSpent)}</div>
                </div>
                <div className="sp-pulse-sub">
                  {categories.length} categor{categories.length === 1 ? 'y' : 'ies'}
                  &nbsp;·&nbsp;
                  {events.length} transaction{events.length !== 1 ? 's' : ''}
                </div>
              </div>
              <div className="sp-pulse-stats">
                <div className="sp-stat">
                  <div className="sp-stat-val">{fmt$(totalSpent / Math.max(new Date().getDate(), 1))}</div>
                  <div className="sp-stat-label">avg/day actual</div>
                </div>
                {topCat && (
                  <div className="sp-stat">
                    <div className="sp-stat-val" style={{ color: catCfg(topCat.category).color }}>
                      {topCat.category.charAt(0).toUpperCase() + topCat.category.slice(1)}
                    </div>
                    <div className="sp-stat-label">top category</div>
                  </div>
                )}
              </div>
            </div>

            {/* Bar chart */}
            <SpendingChart days={dailyData} eventsByDate={eventsByDate} />

            {/* Category color key */}
            {activeCats.length > 0 && (
              <div className="sp-cat-key">
                {activeCats.map(cat => (
                  <div key={cat} className="sp-cat-key-item">
                    <div className="sp-cat-key-dot" style={{ background: catCfg(cat).color }} />
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </div>
                ))}
                <div className="sp-cat-key-item" style={{ marginLeft: 'auto' }}>
                  <div className="sp-cat-key-dot" style={{ background: '#e9e9e9', border: '1px solid #e5e7eb' }} />
                  Upcoming
                </div>
              </div>
            )}
          </div>

          {/* ── Inline Ask Dragun prompt ── */}
          {topCat && (
            <button
              className="sp-inline-prompt"
              onClick={() => askAbout(`My top spending category is ${topCat.category} at ${fmt$(topCat.amount)} (${topCat.pct}% of total). Can you help me understand this and suggest ways to reduce it?`)}
            >
              <span className="sp-prompt-icon">💬</span>
              <span className="sp-prompt-text">
                <strong>{topCat.category.charAt(0).toUpperCase() + topCat.category.slice(1)}</strong>
                {' '}is your top category at {fmt$(topCat.amount)} — ask Dragun how to reduce it
              </span>
              <span className="sp-prompt-arrow">→</span>
            </button>
          )}

          {/* ── Category leaderboard ── */}
          <div className="section-label" style={{ marginTop: 20 }}>
            By Category{' '}
            <span className="sp-label-hint">· click to see transactions</span>
          </div>

          {categories.length === 0 ? (
            <div className="sp-empty">No spending data yet for this period.</div>
          ) : (
            <div className="sp-cat-board">
              {categories.map((cat, i) => (
                <CatRow
                  key={cat.category}
                  cat={cat.category}
                  amount={cat.amount}
                  pct={Math.round(cat.pct * 100)}
                  rank={i + 1}
                  maxAmount={maxCatAmt}
                  events={events}
                  onAsk={(label) => askAbout(`Tell me about my ${label} spending this ${period === 'week' ? 'week' : 'month'} and how I can improve.`)}
                />
              ))}
            </div>
          )}
        </>
      )}

      <div style={{ height: 40 }} />
    </div>
  )
}
