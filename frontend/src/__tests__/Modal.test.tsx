import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { describe, it, expect } from 'vitest'
import { Modal } from '../Modal'

// A parent that re-renders on every keystroke and passes a FRESH `children`
// element each render — mirrors how SetupWizard uses <Modal>. This is the exact
// condition under which the buggy focus-trap effect (deps [isOpen, children])
// re-ran per keystroke and stole focus back to the primary-action button.
function TypingHarness() {
  const [text, setText] = useState('')
  return (
    <Modal isOpen onClose={() => {}} primaryAction={{ label: 'OK', onClick: () => {} }}>
      <input
        data-testid="typed-field"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    </Modal>
  )
}

describe('Modal focus trap', () => {
  it('does not steal focus from an input while typing', () => {
    render(<TypingHarness />)
    const field = screen.getByTestId('typed-field') as HTMLInputElement

    // Initial focus lands on the primary action; move it into the text field.
    field.focus()
    expect(document.activeElement).toBe(field)

    // Type a character — the harness re-renders with a fresh children element.
    fireEvent.change(field, { target: { value: 'h' } })
    expect(document.activeElement).toBe(field) // buggy code re-focuses the OK button here

    fireEvent.change(field, { target: { value: 'he' } })
    expect(document.activeElement).toBe(field)
  })
})

// A parent that re-renders on an unrelated timer/websocket-style tick, passing
// a FRESH inline `onClose` each time — mirrors how App.tsx renders SetupWizard
// (`onClose={() => setShowSetupWizard(false)}`, recreated every App re-render,
// which happens every few seconds off fleet websocket frames). This is the
// condition the shipped focus-restore effect (deps [isOpen, onClose]) reran
// under: parent re-render -> effect cleanup fires -> focuses whatever had
// focus BEFORE the modal opened -> setup re-runs and re-captures THAT as the
// new "previous" element -> the modal's own input never gets focus back.
function RerenderHarness() {
  const [tick, setTick] = useState(0)
  return (
    <div>
      <button data-testid="trigger">Open</button>
      <Modal isOpen onClose={() => setTick((t) => t + 1)}>
        <input data-testid="modal-field" />
      </Modal>
      <button data-testid="force-rerender" onClick={() => setTick((t) => t + 1)}>
        {tick}
      </button>
    </div>
  )
}

describe('Modal focus-restore effect', () => {
  it('does not yank focus back to the pre-open trigger on an unrelated parent re-render', () => {
    render(<RerenderHarness />)
    // A real trigger element must hold focus before Modal's effect first runs,
    // so previousActiveElementRef captures something non-inert (in jsdom, the
    // default activeElement is <body>, which no-ops on .focus() and would mask
    // this bug entirely — see the sibling "typing" test's own comment).
    const trigger = screen.getByTestId('trigger') as HTMLButtonElement
    trigger.focus()

    const field = screen.getByTestId('modal-field') as HTMLInputElement
    field.focus()
    expect(document.activeElement).toBe(field)

    // Force a parent re-render that recreates onClose (identity change only,
    // isOpen stays true) — nothing the user did should move focus here.
    fireEvent.click(screen.getByTestId('force-rerender'))
    expect(document.activeElement).toBe(field)
  })
})
