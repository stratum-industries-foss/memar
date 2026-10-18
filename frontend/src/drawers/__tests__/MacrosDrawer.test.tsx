import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import MacrosDrawer from '../MacrosDrawer'
import * as useMacrosStateModule from '../useMacrosState'
import type { MacrosState } from '../useMacrosState'
import type { DrawerProps } from '../../App'


import { AppDrawerContext } from '../../context/AppContext'
import { render as rtlRender } from '@testing-library/react'

// The drawer reads searchTerm/setSearchTerm from the app context; render it inside one,
// as App.tsx does. Without it useAppDrawer() correctly throws.
function renderWithContext(ui: React.ReactElement, overrides: Record<string, unknown> = {}) {
  const value = {
    printerId: 'printer1',
    searchTerm: '',
    setSearchTerm: () => {},
    ...overrides,
  } as any
  return rtlRender(<AppDrawerContext.Provider value={value}>{ui}</AppDrawerContext.Provider>)
}

// Mock the useMacrosState hook
vi.mock('../useMacrosState', () => ({
  useMacrosState: vi.fn(),
}))

// Mock API calls
vi.mock('../../api', () => ({
  apiFetch: vi.fn(),
}))

describe('MacrosDrawer', () => {
  const mockPrinter = {
    name: 'printer1',
    capability: { machine_type: 'fdm' },
    macros: [],
  }

  const mockMacrosState: MacrosState = {
    showPrivateMacros: false,
    setShowPrivateMacros: vi.fn(),
    macroExpanded: null,
    setMacroExpanded: vi.fn(),
    macroParams: {},
    setMacroParams: vi.fn(),
    macroTypedParams: {},
    setMacroTypedParams: vi.fn(),
    visibleMacros: [],
    privateMacroCount: 0,
    macroGroups: [],
    runMacroWithParams: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useMacrosStateModule.useMacrosState).mockReturnValue(
      mockMacrosState
    )
  })

  it('renders null when no printer selected', () => {
    const props: DrawerProps = { printerId: 'printer1' }
    const { container } = renderWithContext(<MacrosDrawer {...props} currentPrinter={null} />)
    expect(container.querySelector('.drawer-section')).toBeInTheDocument()
    expect(screen.getByText('No printer selected')).toBeInTheDocument()
  })

  it('renders macros drawer with title', () => {
    const props: DrawerProps = { printerId: 'printer1', currentPrinter: mockPrinter }
    renderWithContext(<MacrosDrawer {...props} />)
    expect(screen.getByText('Macros')).toBeInTheDocument()
  })

  it('renders "No macros detected" when no macros available', () => {
    vi.mocked(useMacrosStateModule.useMacrosState).mockReturnValue({
      ...mockMacrosState,
      visibleMacros: [],
      macroGroups: [],
    })

    const props: DrawerProps = { printerId: 'printer1', currentPrinter: mockPrinter }
    renderWithContext(<MacrosDrawer {...props} />)
    expect(screen.getByText('No macros detected.')).toBeInTheDocument()
  })

  it('renders macro groups with categories', () => {
    const testMacro1 = {
      name: 'HEAT_NOZZLE',
      params: {},
      color: undefined,
    }
    const testMacro2 = {
      name: 'HOME_ALL',
      params: {},
      color: undefined,
    }

    // Need multiple groups for category headers to show
    vi.mocked(useMacrosStateModule.useMacrosState).mockReturnValue({
      ...mockMacrosState,
      visibleMacros: [testMacro1, testMacro2],
      macroGroups: [['HEATING', [testMacro1]], ['MOVEMENT', [testMacro2]]],
    })

    const props: DrawerProps = { printerId: 'printer1', currentPrinter: mockPrinter }
    renderWithContext(<MacrosDrawer {...props} />)

    expect(screen.getByText('HEATING')).toBeInTheDocument()
    expect(screen.getByText('MOVEMENT')).toBeInTheDocument()
    expect(screen.getByText('HEAT_NOZZLE')).toBeInTheDocument()
    expect(screen.getByText('HOME_ALL')).toBeInTheDocument()
  })

  it('expands macro when clicked', () => {
    const testMacro = {
      name: 'TEST_MACRO',
      params: {},
      color: undefined,
    }

    const setMacroExpanded = vi.fn()

    vi.mocked(useMacrosStateModule.useMacrosState).mockReturnValue({
      ...mockMacrosState,
      visibleMacros: [testMacro],
      macroGroups: [['TEST', [testMacro]]],
      setMacroExpanded,
      macroExpanded: null,
    })

    const props: DrawerProps = { printerId: 'printer1', currentPrinter: mockPrinter }
    renderWithContext(<MacrosDrawer {...props} />)

    const macroButton = screen.getByText('TEST_MACRO')
    fireEvent.click(macroButton)

    expect(setMacroExpanded).toHaveBeenCalledWith('TEST_MACRO')
  })

  it('shows Run button only when canWrite is true', () => {
    const testMacro = {
      name: 'TEST_MACRO',
      params: {},
      color: undefined,
    }

    vi.mocked(useMacrosStateModule.useMacrosState).mockReturnValue({
      ...mockMacrosState,
      visibleMacros: [testMacro],
      macroGroups: [['TEST', [testMacro]]],
      macroExpanded: 'TEST_MACRO',
    })

    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockPrinter,
      canWrite: true,
    }
    const { rerender } = renderWithContext(<MacrosDrawer {...props} />)

    expect(screen.getByLabelText('Run TEST_MACRO')).toBeInTheDocument()

    // Re-render with canWrite=false
    rerender(<AppDrawerContext.Provider value={{ printerId: 'printer1', searchTerm: '', setSearchTerm: () => {} } as any}><MacrosDrawer {...props} canWrite={false} /></AppDrawerContext.Provider>)
    expect(screen.queryByLabelText('Run TEST_MACRO')).not.toBeInTheDocument()
  })
})
