import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR = 'a, button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Focus trap hook for modal overlays.
 * Traps Tab/Shift+Tab within the element, stores/restores previous focus.
 */
export function useFocusTrap<T extends HTMLElement>(isOpen: boolean): React.RefObject<T> {
  const ref = useRef<T>(null)
  const previousActiveRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!isOpen) return

    // Store the element that had focus before opening
    previousActiveRef.current = document.activeElement as HTMLElement

    // Focus the first focusable element inside the container
    const el = ref.current
    if (el) {
      const focusable = el.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      if (focusable.length > 0) {
        focusable[0].focus()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !ref.current) return

      const focusable = ref.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey) {
        // Shift+Tab from first -> wrap to last
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        // Tab from last -> wrap to first
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      // Restore focus to the element that triggered the overlay
      if (previousActiveRef.current?.focus) {
        previousActiveRef.current.focus()
      }
    }
  }, [isOpen])

  return ref
}
