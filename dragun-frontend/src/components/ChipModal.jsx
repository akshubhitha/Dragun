import { useEffect, useRef } from 'react'
import { chat } from '../api.js'

/**
 * ChipModal — a lightweight slide-up modal for quick category actions.
 * Triggered by clicking a spending chip on the Overview page.
 */
export default function ChipModal({ category, userId, onClose }) {
  const overlayRef = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleOverlayClick = (e) => {
    if (e.target === overlayRef.current) onClose()
  }

  const handleAsk = async () => {
    try {
      await chat(userId, `What did I spend on ${category} this month?`)
    } catch {}
    onClose()
    window.location.href = '/chat'
  }

  return (
    <div className="modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="modal-sheet">
        <div className="modal-handle" />
        <h3 className="modal-title">{category}</h3>
        <p className="modal-subtitle">What would you like to do?</p>
        <div className="modal-actions">
          <button className="modal-action-btn" onClick={handleAsk}>
            <i className="ti ti-message-circle-2" />
            Ask about {category} spending
          </button>
          <button className="modal-action-btn secondary" onClick={onClose}>
            <i className="ti ti-x" />
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
