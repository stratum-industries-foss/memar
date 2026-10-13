import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import JogDrawer from '../JogDrawer'
import * as useJogStateModule from '../useJogState'
import type { DrawerProps } from '../../App'

// Mock the useJogState hook
vi.mock('../useJogState', () => ({
  useJogState: vi.fn(),
}))

// Mock machine types
vi.mock('../machineTypes', () => ({
  isCncMachine: vi.fn((type) => type?.startsWith('cnc_')),
}))

// Mock API calls
vi.mock('../../api', () => ({
  apiFetch: vi.fn(),
}))

describe('JogDrawer', () => {
  const mockFdmPrinter = {
    name: 'printer1',
    capability: { machine_type: 'fdm' },
  }

  const mockCncPrinter = {
    name: 'cnc1',
    capability: { machine_type: 'cnc_mill' },
  }

  const mockUseJogState = {
    jogDistance: '1',
    setJogDistance: vi.fn(),
    jogFeedrate: '3000',
    setJogFeedrate: vi.fn(),
    busy: false,
    runJog: vi.fn(),
    runHome: vi.fn(),
    handleMotionCheckClick: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useJogStateModule.useJogState).mockReturnValue(mockUseJogState)
  })

  it('returns null when canWrite is false', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: false,
    }
    const { container } = render(<JogDrawer {...props} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders null when no printer selected', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: null,
      canWrite: true,
    }
    const { container } = render(<JogDrawer {...props} />)
    // Should render the drawer section with "No printer selected"
    const section = container.querySelector('.drawer-section')
    expect(section).toBeInTheDocument()
    expect(screen.getByText('No printer selected')).toBeInTheDocument()
  })

  it('renders jog drawer with controls', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.getByText('Jog controls')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog distance (mm)')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog feedrate (mm/min)')).toBeInTheDocument()
  })

  it('renders D-pad controls with arrow buttons', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.getByLabelText('Jog X- (left)')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog X+ (right)')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog Y+ (forward)')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog Y- (back)')).toBeInTheDocument()
  })

  it('renders Z-axis controls', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.getByLabelText('Jog Z+ (up)')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog Z- (down)')).toBeInTheDocument()
  })

  it('renders extruder controls only for FDM machines', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.getByLabelText('Extrude (E+)')).toBeInTheDocument()
    expect(screen.getByLabelText('Retract (E-)')).toBeInTheDocument()
  })

  it('does not render extruder controls for CNC machines', () => {
    const props: DrawerProps = {
      printerId: 'cnc1',
      currentPrinter: mockCncPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.queryByLabelText('Extrude (E+)')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Retract (E-)')).not.toBeInTheDocument()
  })

  it('calls runJog with correct parameters when jog button clicked', () => {
    const runJog = vi.fn()
    vi.mocked(useJogStateModule.useJogState).mockReturnValue({
      ...mockUseJogState,
      runJog,
    })

    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    const xPlusButton = screen.getByLabelText('Jog X+ (right)')
    fireEvent.click(xPlusButton)

    expect(runJog).toHaveBeenCalledWith('X', 1)
  })

  it('renders quick distance buttons', () => {
    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    expect(screen.getByLabelText('Jog 0.1mm')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog 1mm')).toBeInTheDocument()
    expect(screen.getByLabelText('Jog 10mm')).toBeInTheDocument()
  })

  it('disables jog controls when busy', () => {
    vi.mocked(useJogStateModule.useJogState).mockReturnValue({
      ...mockUseJogState,
      busy: true,
    })

    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    const distanceInput = screen.getByLabelText('Jog distance (mm)') as HTMLInputElement
    expect(distanceInput.disabled).toBe(true)

    const xPlusButton = screen.getByLabelText('Jog X+ (right)') as HTMLButtonElement
    expect(xPlusButton.disabled).toBe(true)
  })

  it('calls handleMotionCheckClick when motion check button clicked', () => {
    const handleMotionCheckClick = vi.fn()
    vi.mocked(useJogStateModule.useJogState).mockReturnValue({
      ...mockUseJogState,
      handleMotionCheckClick,
    })

    const props: DrawerProps = {
      printerId: 'printer1',
      currentPrinter: mockFdmPrinter,
      canWrite: true,
    }
    render(<JogDrawer {...props} />)

    const motionCheckButton = screen.getByLabelText('Run motion check')
    fireEvent.click(motionCheckButton)

    expect(handleMotionCheckClick).toHaveBeenCalled()
  })
})
