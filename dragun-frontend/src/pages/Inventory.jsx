import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { getInventory } from '../api.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

const CAT_CONFIG = {
  electronics:  { color: '#5b8dd9', bg: '#eef2fc', emoji: '💻' },
  sports:       { color: '#6BAE78', bg: '#f0f7f2', emoji: '🏋️' },
  appliances:   { color: '#c9922a', bg: '#fef3e2', emoji: '🍳' },
  furniture:    { color: '#9b8dd9', bg: '#f3f0fc', emoji: '🪑' },
  clothing:     { color: '#c4547a', bg: '#fff0f6', emoji: '👕' },
  tools:        { color: '#6b7280', bg: '#f3f4f6', emoji: '🔧' },
  kitchen:      { color: '#c9922a', bg: '#fef3e2', emoji: '🍳' },
  audio:        { color: '#5b8dd9', bg: '#eef2fc', emoji: '🎧' },
  photography:  { color: '#5b8dd9', bg: '#eef2fc', emoji: '📷' },
  gaming:       { color: '#9b8dd9', bg: '#f3f0fc', emoji: '🎮' },
  fitness:      { color: '#6BAE78', bg: '#f0f7f2', emoji: '🏃' },
  transport:    { color: '#5b8dd9', bg: '#eef2fc', emoji: '🚗' },
}

const ITEM_EMOJI = {
  laptop: '💻', macbook: '💻', computer: '🖥️', monitor: '🖥️',
  phone: '📱', iphone: '📱', samsung: '📱',
  camera: '📷', lens: '📷',
  headphone: '🎧', airpod: '🎧', earphone: '🎧', speaker: '🔊',
  bike: '🚲', bicycle: '🚲',
  chair: '🪑', desk: '🖥️', table: '🪑',
  watch: '⌚', mixer: '🍳', kettle: '☕', coffee: '☕',
  keyboard: '⌨️', mouse: '🖱️', tablet: '📱', ipad: '📱',
  tv: '📺', television: '📺',
  vacuum: '🧹', washer: '🫧', dryer: '🫧',
  guitar: '🎸', piano: '🎹',
  treadmill: '🏃', weights: '🏋️',
}

function itemEmoji(name, tags) {
  const lower = name.toLowerCase()
  for (const [key, emoji] of Object.entries(ITEM_EMOJI)) {
    if (lower.includes(key)) return emoji
  }
  if (tags?.length) {
    const tag = tags[0].toLowerCase()
    return CAT_CONFIG[tag]?.emoji || '📦'
  }
  return '📦'
}

function catCfg(tags) {
  if (!tags?.length) return { color: '#6b7280', bg: '#f3f4f6' }
  const tag = tags[0].toLowerCase()
  return CAT_CONFIG[tag] || { color: '#6b7280', bg: '#f3f4f6' }
}

function catLabel(tags) {
  if (!tags?.length) return 'Other'
  return tags[0].charAt(0).toUpperCase() + tags[0].slice(1)
}

function fmt$(n) {
  return '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtDate(isoStr) {
  if (!isoStr) return ''
  return new Date(isoStr).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

function toTitleCase(str) {
  return str.replace(/\b\w/g, c => c.toUpperCase())
}

// ── Item card ─────────────────────────────────────────────────────────────────

function ItemCard({ item, onAsk }) {
  const cfg        = catCfg(item.tags)
  const emoji      = itemEmoji(item.item_normalized, item.tags)
  const totalValue = (item.avg_unit_cost || 0) * item.current_quantity
  const label      = toTitleCase(item.item_normalized)

  return (
    <div className="inv-card">
      <div className="inv-card-actions">
        <button
          className="inv-action-btn"
          onClick={() => onAsk(item)}
        >Ask Dragun</button>
      </div>

      <div className="inv-card-icon-area">
        <div className="inv-emoji-wrap" style={{ background: cfg.bg }}>{emoji}</div>
        <div className="inv-card-header">
          <div className="inv-item-name" title={label}>{label}</div>
          <div className="inv-badges">
            <span className="inv-cat-badge" style={{ background: cfg.bg, color: cfg.color }}>
              {catLabel(item.tags)}
            </span>
            {item.current_quantity > 1 && (
              <span className="inv-qty-badge">×{item.current_quantity}</span>
            )}
          </div>
        </div>
      </div>

      <div className="inv-value-area">
        {totalValue > 0 ? (
          <>
            <div className="inv-current-val">{fmt$(totalValue)}</div>
            <div className="inv-paid-row">
              {item.current_quantity > 1
                ? `${fmt$(item.avg_unit_cost)} avg · ${item.current_quantity} units`
                : `paid ${fmt$(item.avg_unit_cost)}`}
            </div>
          </>
        ) : (
          <div className="inv-current-val inv-current-val--dim">—</div>
        )}
        <div className="inv-acquired">
          {item.first_seen
            ? `First logged ${fmtDate(item.first_seen)}`
            : item.last_purchased
              ? `Last purchased ${fmtDate(item.last_purchased)}`
              : 'In your hoard'}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Inventory() {
  const { session } = useAuth()
  const navigate    = useNavigate()
  const [items,   setItems]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [search,  setSearch]  = useState('')

  useEffect(() => {
    async function load() {
      try {
        const res = await getInventory(session.user_id)
        // Show only durable items in the catalog (not consumables like groceries)
        const durable = (res.inventory || []).filter(
          i => i.lifespan_type === 'durable' || i.lifespan_type === 'DURABLE'
        )
        setItems(durable)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [session.user_id])

  const askAbout = (item) => {
    const label = toTitleCase(item.item_normalized)
    navigate('/chat', {
      state: {
        prefill: `Tell me about my ${label}${item.avg_unit_cost ? ` (paid ${fmt$(item.avg_unit_cost)})` : ''} — what's a fair resale value and should I upgrade?`
      }
    })
  }

  const askGeneral = (prefill) => navigate('/chat', { state: { prefill } })

  // Filter
  const filtered = search
    ? items.filter(i => i.item_normalized.toLowerCase().includes(search.toLowerCase())
        || i.tags?.some(t => t.toLowerCase().includes(search.toLowerCase())))
    : items

  // Summary stats
  const totalValue   = items.reduce((s, i) => s + (i.avg_unit_cost || 0) * i.current_quantity, 0)
  const itemCount    = items.reduce((s, i) => s + i.current_quantity, 0)

  // Category breakdown for pips
  const catTotals = {}
  items.forEach(i => {
    const cat = i.tags?.[0]?.toLowerCase() || 'other'
    catTotals[cat] = (catTotals[cat] || 0) + (i.avg_unit_cost || 0) * i.current_quantity
  })
  const sortedCats = Object.entries(catTotals).sort((a, b) => b[1] - a[1]).slice(0, 4)
  const maxCatVal  = sortedCats[0]?.[1] || 1

  const PIP_COLORS = ['#5b8dd9', '#6BAE78', '#c9922a', '#9b8dd9']

  return (
    <div className="inv-wrap">

      {/* ── Scrollable content ── */}
      <div className="inv-scroll">

        {/* Header */}
        <div className="inv-page-header">
          <div>
            <h1 className="page-title">Inventory</h1>
            <div className="inv-page-sub">Your hoard — durable things you own and what they're worth</div>
          </div>
          <div className="inv-header-actions">
            <div className="inv-search-wrap">
              <span className="inv-search-icon">🔍</span>
              <input
                className="inv-search-input"
                type="text"
                placeholder="Search items…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <button
              className="bgt-header-btn"
              onClick={() => askGeneral('I want to add a new item to my inventory. Help me log it.')}
            >
              ＋ Add item
            </button>
          </div>
        </div>

        {loading ? (
          <div className="bgt-loading">Loading your hoard…</div>
        ) : error ? (
          <div className="bgt-error">{error}</div>
        ) : (
          <>
            {/* Summary bar */}
            {items.length > 0 && (
              <div className="inv-summary-bar">
                <div className="inv-stat">
                  <div className="inv-stat-val">{itemCount}</div>
                  <div className="inv-stat-label">items tracked</div>
                </div>
                {totalValue > 0 && (
                  <div className="inv-stat">
                    <div className="inv-stat-val inv-stat-val--green">{fmt$(totalValue)}</div>
                    <div className="inv-stat-label">total paid value</div>
                  </div>
                )}
                <div className="inv-stat">
                  <div className="inv-stat-val">{sortedCats.length}</div>
                  <div className="inv-stat-label">categories</div>
                </div>

                {/* Category pips */}
                {sortedCats.length > 0 && (
                  <div className="inv-pips">
                    {sortedCats.map(([cat, val], i) => (
                      <div className="inv-pip-row" key={cat}>
                        <span className="inv-pip-label">
                          {cat.charAt(0).toUpperCase() + cat.slice(1)}
                        </span>
                        <div className="inv-pip-track">
                          <div
                            className="inv-pip-fill"
                            style={{
                              width: `${(val / maxCatVal) * 100}%`,
                              background: PIP_COLORS[i % PIP_COLORS.length],
                            }}
                          />
                        </div>
                        <span className="inv-pip-val">{fmt$(val)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Item grid */}
            {filtered.length === 0 && items.length > 0 ? (
              <div className="bgt-empty">No items match "{search}"</div>
            ) : filtered.length === 0 ? (
              <div className="inv-empty">
                <div className="inv-empty-icon">📦</div>
                <div className="inv-empty-title">Your hoard is empty</div>
                <div className="inv-empty-sub">
                  Tell Dragun what you bought and it'll track your gear automatically.
                </div>
                <button
                  className="bgt-header-btn"
                  onClick={() => askGeneral('I want to log something I own. Help me add it to my inventory.')}
                  style={{ marginTop: 16 }}
                >
                  Tell Dragun what you own
                </button>
              </div>
            ) : (
              <div className="inv-grid">
                {filtered.map((item, idx) => (
                  <ItemCard key={`${item.item_normalized}-${idx}`} item={item} onAsk={askAbout} />
                ))}

                {/* Add item tile */}
                <button
                  className="inv-add-card"
                  onClick={() => askGeneral('I want to log a new item to my inventory.')}
                >
                  <div className="inv-add-icon">＋</div>
                  <div className="inv-add-label">Add item</div>
                  <div className="inv-add-sub">or tell Dragun what you bought</div>
                </button>
              </div>
            )}

            <div style={{ height: 16 }} />
          </>
        )}
      </div>

      {/* ── Sticky footer CTA ── */}
      <div className="inv-footer-bar">
        <span className="inv-footer-icon">✦</span>
        <span className="inv-footer-text">
          <strong>Ask Dragun</strong> to log a new item, look up a resale value, or scan a barcode
        </span>
        <div className="inv-footer-actions">
          <button
            className="inv-footer-btn ghost"
            onClick={() => askGeneral('Can you help me scan or identify an item to add to my inventory?')}
          >
            📷 Scan / identify
          </button>
          <button
            className="inv-footer-btn primary"
            onClick={() => askGeneral("What's in my inventory and what's it worth?")}
          >
            Ask Dragun →
          </button>
        </div>
      </div>

    </div>
  )
}
