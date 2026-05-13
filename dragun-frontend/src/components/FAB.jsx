export default function FAB({ onClick }) {
  return (
    <button className="fab-chat" onClick={onClick} aria-label="Open chat">
      <i className="ti ti-message-circle-2" />
    </button>
  )
}
