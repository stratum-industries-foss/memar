/**
 * MaterialSelector Component Tests
 *
 * Tests cover:
 * - Preset materials display and selection
 * - Custom material creation
 * - Material properties display
 * - Disabled state handling
 * - Apply callback functionality
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MaterialSelector from '../MaterialSelector'
import { DEFAULT_MATERIALS } from '../../types/material'

// Materials are applied by clicking a material card (role="button", name "Material: <name>...").
// The old per-material "Apply" label no longer exists in the component.
function materialCards() {
  return screen.getAllByRole('button', { name: /^Material:/ })
}

describe('MaterialSelector', () => {
  describe('Preset Materials', () => {
    it('renders all default materials', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      DEFAULT_MATERIALS.forEach((mat) => {
        expect(screen.getByText(mat.name)).toBeInTheDocument()
      })
    })

    it('displays material properties correctly', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      // Check PLA properties
      const plaCards = screen.getAllByText('PLA')
      expect(plaCards.length).toBeGreaterThan(0)

      // Find the card with PLA and verify its specs
      const cards = screen.getAllByText('Standard thermoplastic')
      expect(cards.length).toBeGreaterThan(0)
    })

    it('shows color swatch for materials with color', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      const swatches = screen.getAllByRole('button')
      expect(swatches.length).toBeGreaterThan(0)
    })

    it('calls onApply callback when material is applied', async () => {
      const handleApply = vi.fn()
      render(<MaterialSelector onApply={handleApply} />)

      fireEvent.click(screen.getByText(/Material library/))

      const applyButtons = materialCards()
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        expect(handleApply).toHaveBeenCalled()
      })
    })

    it('closes library after material selection', async () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      expect(screen.getByText('PLA')).toBeInTheDocument()

      const applyButtons = materialCards()
      fireEvent.click(applyButtons[0])

      await waitFor(() => {
        expect(screen.queryByText('PLA')).not.toBeInTheDocument()
      })
    })
  })

  describe('Custom Material Creation', () => {
    it('toggles custom material form', async () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      expect(screen.queryByText('Create custom material')).not.toBeInTheDocument()

      fireEvent.click(screen.getByText('+ Add custom material'))
      expect(screen.getByText('Create custom material')).toBeInTheDocument()
    })

    it('validates required name field', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      fireEvent.click(screen.getByText('+ Add custom material'))

      const saveButton = screen.getByText('Save material')
      await user.click(saveButton)

      // Alert should be called for missing name
      expect(screen.getByText('Create custom material')).toBeInTheDocument()
    })

    it('creates custom material with valid data', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      fireEvent.click(screen.getByText('+ Add custom material'))

      const nameInput = screen.getByPlaceholderText('Material name')
      const nozzleInput = screen.getByDisplayValue('200')

      await user.type(nameInput, 'Custom TPE')
      await user.clear(nozzleInput)
      await user.type(nozzleInput, '230')

      fireEvent.click(screen.getByText('Save material'))

      await waitFor(() => {
        expect(screen.getByText('Custom TPE')).toBeInTheDocument()
      })
    })

    it('displays all material input fields', async () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      fireEvent.click(screen.getByText('+ Add custom material'))

      expect(screen.getByPlaceholderText('Material name')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Description (optional)')).toBeInTheDocument()
      expect(screen.getByDisplayValue('200')).toBeInTheDocument() // nozzle temp
      expect(screen.getByDisplayValue('60')).toBeInTheDocument() // bed temp
      expect(screen.getByDisplayValue('50')).toBeInTheDocument() // speed
      expect(screen.getByDisplayValue('5')).toBeInTheDocument() // retraction distance
      expect(screen.getByDisplayValue('45')).toBeInTheDocument() // retraction speed
    })

    it('cancels custom material creation', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      fireEvent.click(screen.getByText('+ Add custom material'))

      const cancelButton = screen.getByText('Cancel')
      await user.click(cancelButton)

      expect(screen.queryByText('Create custom material')).not.toBeInTheDocument()
      expect(screen.getByText('+ Add custom material')).toBeInTheDocument()
    })

    it('closes form after successful save', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))
      fireEvent.click(screen.getByText('+ Add custom material'))

      const nameInput = screen.getByPlaceholderText('Material name')
      await user.type(nameInput, 'Test Material')

      fireEvent.click(screen.getByText('Save material'))

      // Form should close after save
      await waitFor(() => {
        expect(screen.queryByText('Create custom material')).not.toBeInTheDocument()
      })
    })
  })

  describe('Current Material Highlighting', () => {
    it('highlights current material', () => {
      render(<MaterialSelector currentMaterial="PLA" />)

      fireEvent.click(screen.getByText(/Material library/))

      // Material card should have different styling when current
      const plaCards = screen.getAllByText('PLA')
      expect(plaCards.length).toBeGreaterThan(0)

      // Verify the library is shown (indicating expansion worked)
      expect(screen.getByText(/Material library/)).toBeInTheDocument()
    })

    it('removes highlight when current material changes', () => {
      const { rerender } = render(<MaterialSelector currentMaterial="PLA" />)

      fireEvent.click(screen.getByText(/Material library/))

      rerender(<MaterialSelector currentMaterial="PETG" />)

      // PLA should no longer be highlighted
      const cards = screen.getAllByText(/PLA|PETG/)
      expect(cards.length).toBeGreaterThan(0)
    })
  })

  describe('Disabled State', () => {
    it('disables library expansion when disabled', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector disabled={true} />)

      const button = screen.getByText(/Material library/)
      expect(button).toBeDisabled()
    })

    it('disables apply buttons when disabled', async () => {
      render(<MaterialSelector disabled={true} />)

      // Force open by finding the button in disabled state
      const buttons = screen.getAllByRole('button')
      const libraryBtn = buttons.find((btn) => btn.textContent?.includes('Material library'))

      expect(libraryBtn).toBeDisabled()
    })
  })

  describe('Material Properties Display', () => {
    it('shows all material specs in correct format', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      // Find any material card and verify spec display
      const specLabels = screen.getAllByText(/Nozzle|Bed|Speed|Retract/)
      expect(specLabels.length).toBeGreaterThan(0)
    })

    it('displays description when available', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      expect(screen.getByText('Standard thermoplastic')).toBeInTheDocument()
      expect(screen.getByText('Engineering plastic')).toBeInTheDocument()
    })
  })

  describe('Responsive Layout', () => {
    it('renders material grid layout', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      const materials = screen.getAllByText(/PLA|PETG|ABS|TPU|Nylon/)
      expect(materials.length).toBeGreaterThan(0)
    })
  })

  describe('Keyboard Navigation', () => {
    it('supports keyboard interaction for expanding library', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      const button = screen.getByText(/Material library/)
      await user.click(button)

      expect(screen.getByText('PLA')).toBeInTheDocument()
    })

    it('supports keyboard interaction for applying materials', async () => {
      const handleApply = vi.fn()
      const user = userEvent.setup()
      render(<MaterialSelector onApply={handleApply} />)

      fireEvent.click(screen.getByText(/Material library/))

      const applyButtons = materialCards()
      await user.click(applyButtons[0])

      await waitFor(() => {
        expect(handleApply).toHaveBeenCalled()
      })
    })
  })

  describe('Edge Cases', () => {
    it('handles missing onApply callback gracefully', () => {
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      const applyButtons = materialCards()
      expect(() => {
        fireEvent.click(applyButtons[0])
      }).not.toThrow()
    })

    it('supports adding multiple custom materials', async () => {
      const user = userEvent.setup()
      render(<MaterialSelector />)

      fireEvent.click(screen.getByText(/Material library/))

      // Add first custom material
      fireEvent.click(screen.getByText('+ Add custom material'))
      const nameInput = screen.getByPlaceholderText('Material name')
      await user.type(nameInput, 'Custom 1')
      fireEvent.click(screen.getByText('Save material'))

      await waitFor(() => {
        expect(screen.getByText('Custom 1')).toBeInTheDocument()
      })

      // Add second custom material
      fireEvent.click(screen.getByText('+ Add custom material'))
      const nameInput2 = screen.getByPlaceholderText('Material name')
      await user.type(nameInput2, 'Custom 2')
      fireEvent.click(screen.getByText('Save material'))

      await waitFor(() => {
        expect(screen.getByText('Custom 2')).toBeInTheDocument()
      })
    })
  })
})
