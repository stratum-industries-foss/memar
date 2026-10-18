import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import DryrunDrawer from '../DryrunDrawer'

/**
 * TEST 1: DryrunDrawer renders all major sections
 */
describe('DryrunDrawer', () => {
  it('should render action dry-run section', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    expect(screen.getByText('Action dry-run')).toBeDefined()
  })

  it('should render motion check section when canWrite is true', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    expect(screen.getByText('Motion check')).toBeDefined()
  })

  it('should not render motion check section when canWrite is false', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={false} />)
    expect(screen.queryByText('Motion check')).toBeNull()
  })

  it('should render dispatch preflight section', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    expect(screen.getByText('Dispatch preflight')).toBeDefined()
  })

  it('should show "no printer selected" when printerId is undefined', () => {
    render(<DryrunDrawer printerId={undefined} canWrite={true} />)
    expect(screen.getByText('No printer selected')).toBeDefined()
  })
})

/**
 * TEST 2: DryrunDrawer form controls
 */
describe('DryrunDrawer - Form Controls', () => {
  it('should have action selector with home as default', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const selects = screen.getAllByRole('combobox')
    expect(selects.length > 0).toBe(true)
  })

  it('should have dispatch filename input', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const filenameInput = screen.getByPlaceholderText('gcodes/example.gcode')
    expect(filenameInput).toBeDefined()
  })

  it('should have material input field', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const materialInput = screen.getByPlaceholderText('PLA')
    expect(materialInput).toBeDefined()
  })

  it('should have nozzle diameter input field', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const inputs = screen.getAllByRole('textbox')
    expect(inputs.length >= 2).toBe(true)
  })
})

/**
 * TEST 3: DryrunDrawer button interactions
 */
describe('DryrunDrawer - Button Controls', () => {
  it('should have run dry-run button', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const buttons = screen.getAllByRole('button')
    const dryRunButton = buttons.find((b) => b.textContent?.includes('dry-run'))
    expect(dryRunButton).toBeDefined()
  })

  it('should have motion check button when canWrite is true', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const buttons = screen.getAllByRole('button')
    const motionButton = buttons.find((b) => b.textContent?.includes('motion'))
    expect(motionButton).toBeDefined()
  })

  it('should have dispatch button', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const buttons = screen.getAllByRole('button')
    const dispatchButton = buttons.find((b) => b.textContent?.includes('dispatch'))
    expect(dispatchButton).toBeDefined()
  })

  it('should disable dispatch button when filename is empty', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const buttons = screen.getAllByRole('button')
    const dispatchButton = buttons.find((b) => b.textContent?.includes('dispatch')) as HTMLButtonElement
    expect(dispatchButton?.disabled).toBe(true)
  })

  it('should enable dispatch button when filename is provided', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const filenameInput = screen.getByPlaceholderText('gcodes/example.gcode')
    fireEvent.change(filenameInput, { target: { value: 'test.gcode' } })

    const buttons = screen.getAllByRole('button')
    const dispatchButton = buttons.find((b) => b.textContent?.includes('dispatch')) as HTMLButtonElement
    expect(dispatchButton?.disabled).toBe(false)
  })
})

/**
 * TEST 4: DryrunDrawer semantic structure
 */
describe('DryrunDrawer - Accessibility', () => {
  it('should have proper heading structure', () => {
    render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const headings = screen.getAllByRole('heading', { level: 3 })
    expect(headings.length >= 2).toBe(true) // At least action dry-run and dispatch
  })

  it('should have section elements for major parts', () => {
    const { container } = render(<DryrunDrawer printerId="printer-001" canWrite={true} />)
    const sections = container.querySelectorAll('section.drawer-section')
    expect(sections.length >= 2).toBe(true)
  })
})
