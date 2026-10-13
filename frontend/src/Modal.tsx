import React, { useEffect, useRef } from 'react'

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  primaryAction?: { label: string; onClick: () => void }
  secondaryAction?: { label: string; onClick: () => void }
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  children,
  primaryAction,
  secondaryAction,
}) => {
  const modalRef = useRef<HTMLDivElement>(null)
  const previousActiveElementRef = useRef<HTMLElement | null>(null)

  // Callers frequently pass an inline onClose (a fresh function every render).
  // Keeping it out of the effect below's deps — read via ref instead — means a
  // parent re-render while the modal is open no longer tears down and re-runs
  // this effect: the old code's cleanup restored focus to whatever triggered
  // the modal, then setup immediately re-captured "current" focus as that same
  // trigger element, so typing in a modal input got yanked back to the
  // trigger on every parent re-render (e.g. SetupWizard, re-rendered by a
  // websocket frame every few seconds while it's open).
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!isOpen) return

    // Store the element that had focus before opening the modal
    previousActiveElementRef.current = document.activeElement as HTMLElement

    // Set body scroll lock
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Escape key listener
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = originalOverflow

      // Restore focus to the element that triggered the modal
      if (previousActiveElementRef.current?.focus) {
        previousActiveElementRef.current.focus()
      }
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen || !modalRef.current) return

    // Set initial focus to the first focusable element (or primary action if available)
    const primaryActionButton = modalRef.current.querySelector<HTMLElement>(
      '[data-testid="modal-primary-action"]'
    )
    if (primaryActionButton) {
      primaryActionButton.focus()
    } else {
      const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length > 0) {
        focusableElements[0].focus()
      }
    }

    // Handle focus trap on Tab/Shift+Tab. Re-compute focusable elements
    // on every keydown so list changes (item add/remove) are reflected.
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return

      const focusableElements = modalRef.current!.querySelectorAll<HTMLElement>(
        'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      if (focusableElements.length === 0) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]

      if (e.shiftKey) {
        // Shift+Tab from first element -> go to last
        if (document.activeElement === firstElement) {
          e.preventDefault()
          lastElement.focus()
        }
      } else {
        // Tab from last element -> go to first
        if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement.focus()
        }
      }
    }

    modalRef.current.addEventListener('keydown', handleKeyDown)

    return () => {
      modalRef.current?.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={modalRef}
        className="modal-content modal-form"
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'modal-title' : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 id="modal-title">{title}</h2>
            <button
              type="button"
              className="modal-close"
              onClick={onClose}
              aria-label="Close modal"
            >
              ×
            </button>
          </div>
        )}
        <div>{children}</div>

        {(primaryAction || secondaryAction) && (
          <div className="modal-actions">
            {secondaryAction && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={secondaryAction.onClick}
              >
                {secondaryAction.label}
              </button>
            )}
            {primaryAction && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={primaryAction.onClick}
                data-testid="modal-primary-action"
              >
                {primaryAction.label}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
