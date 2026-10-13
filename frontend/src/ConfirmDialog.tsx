import React from 'react'

interface ConfirmDialogProps {
  message: string
  onConfirm: () => void
  onCancel: () => void
}

export const ConfirmDialog = React.memo(function ConfirmDialog({ message, onConfirm, onCancel }: ConfirmDialogProps) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="confirm-overlay" onClick={onCancel} role="presentation">
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label="Confirm action"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button className="confirm-cancel" onClick={onCancel} autoFocus>Cancel</button>
          <button className="confirm-ok" onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  )
})
