export default function FAB({ onClick, elevated }) {
  return (
    <button
      className={`fab-chat${elevated ? ' fab-chat--elevated' : ''}`}
      onClick={onClick}
      aria-label="Open chat"
    >
      <i className="ti ti-message-circle-2" />
    </button>
  )
}
