throw new Error('App.new.tsx is not the SPA entry — use App.tsx instead')

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { info, error, debug } from './logging'
import { apiFetch, authState, initializeAuth, setTokens, clearTokens, refreshAccessToken } from './api'
import {
  handleConsoleKey,
  loadConsoleHistory,
  saveConsoleHistory,
  appendConsoleHistory,
  NO_COMPLETION_CYCLE,
  type CompletionCycle,
} from './consoleInput'
import { FloorPlan2D, DevicePosition } from './FloorPlan2D'
import { FloorPlanEditor } from './FloorPlanEditor'
import { FleetToolsModal, QueuePanel, MaintenancePanel, HealthPanel } from './FleetTools'
import { CoolantMetricsPanel } from './CoolantMetricsPanel'
import { CNCMetricsPanel } from './CNCMetricsPanel'
import ThreeDViewer from './ThreeDViewer'
import { ConfirmDialog } from './ConfirmDialog'
import { AlphaAcknowledgeModal } from './AlphaAcknowledgeModal'
import { AdminPanel } from './AdminPanel'
import { SetupWizard } from './SetupWizard'
import { ExcludeObjectsMap, hasPolygonData } from './ExcludeObjectsMap'
import { BedMeshPanel } from './BedMeshPanel'
import type { DrawerProps } from './types/drawer-props'

// Lazy-loaded drawer components (code splitting)
const OverviewDrawer = React.lazy(() => import('./drawers/OverviewDrawer'))
const TemperatureDrawer = React.lazy(() => import('./drawers/TemperatureDrawer'))
const JogDrawer = React.lazy(() => import('./drawers/JogDrawer'))
const MacrosDrawer = React.lazy(() => import('./drawers/MacrosDrawer'))
const FilesDrawer = React.lazy(() => import('./drawers/FilesDrawer'))
const SettingsDrawer = React.lazy(() => import('./drawers/SettingsDrawer'))
const HistoryDrawer = React.lazy(() => import('./drawers/HistoryDrawer'))
const WebcamsDrawer = React.lazy(() => import('./drawers/WebcamsDrawer'))
const DryrunDrawer = React.lazy(() => import('./drawers/DryrunDrawer'))
const TimelapseDrawer = React.lazy(() => import('./drawers/TimelapseDrawer'))
const ConsoleDrawer = React.lazy(() => import('./drawers/ConsoleDrawer'))
const BedmeshDrawer = React.lazy(() => import('./drawers/BedmeshDrawer'))
const QueueDrawer = React.lazy(() => import('./drawers/QueueDrawer'))
const MaintenanceDrawer = React.lazy(() => import('./drawers/MaintenanceDrawer'))
const HealthDrawer = React.lazy(() => import('./drawers/HealthDrawer'))
const CncDrawer = React.lazy(() => import('./drawers/CncDrawer'))
const CoolantDrawer = React.lazy(() => import('./drawers/CoolantDrawer'))
const AnalyticsDrawer = React.lazy(() => import('./drawers/AnalyticsDrawer'))

// Types and context (moved from inline)
export type DrawerSection =
  | 'overview' | 'temperature' | 'jog' | 'macros' | 'files' | 'settings'
  | 'history' | 'webcams' | 'dryrun' | 'timelapse' | 'console' | 'bedmesh'
  | 'queue' | 'maintenance' | 'health' | 'cnc' | 'coolant' | 'analytics'

export type DrawerMessage = {
  text: string
  severity: 'info' | 'warning' | 'error' | 'success'
} | null

export type AuthState = {
  isAuthenticated?: boolean
  canWrite?: boolean
  role?: string
}

export type DrawerContextType = {
  activeSection: DrawerSection | null
  setActiveSection: (section: DrawerSection | null) => void
  drawerMessage: DrawerMessage
  setDrawerMessage: (msg: DrawerMessage) => void
}

export const AppDrawerContext = React.createContext<DrawerContextType | null>(null)

// Printer type
export type Printer = {
  id: string
  name: string
  [key: string]: any
}

// Diagnostics type
export type Diagnostics = {
  [key: string]: any
}

// SetupWizard props
export type SetupWizardProps = {
  onComplete: () => void
}

// FloorPlan2D props
export type FloorPlan2DProps = {
  printer: Printer
}

// AlphaAcknowledgeModal props
export type AlphaAcknowledgeModalProps = {
  onClose: () => void
}

// Drawer component registry
const DRAWER_COMPONENTS: Record<DrawerSection, React.ComponentType<DrawerProps>> = {
  overview: OverviewDrawer,
  temperature: TemperatureDrawer,
  jog: JogDrawer,
  macros: MacrosDrawer,
  files: FilesDrawer,
  settings: SettingsDrawer,
  history: HistoryDrawer,
  webcams: WebcamsDrawer,
  dryrun: DryrunDrawer,
  timelapse: TimelapseDrawer,
  console: ConsoleDrawer,
  bedmesh: BedmeshDrawer,
  queue: QueueDrawer,
  maintenance: MaintenanceDrawer,
  health: HealthDrawer,
  cnc: CncDrawer,
  coolant: CoolantDrawer,
  analytics: AnalyticsDrawer,
}

const DRAWER_NAMES: DrawerSection[] = Object.keys(DRAWER_COMPONENTS) as DrawerSection[]

// Drawer provider wrapper
export function DrawerProvider({ children }: { children: React.ReactNode }) {
  const [activeSection, setActiveSection] = useState<DrawerSection | null>('overview')
  const [drawerMessage, setDrawerMessage] = useState<DrawerMessage>(null)

  const contextValue: DrawerContextType = useMemo(() => ({
    activeSection,
    setActiveSection,
    drawerMessage,
    setDrawerMessage,
  }), [activeSection, drawerMessage])

  return (
    <AppDrawerContext.Provider value={contextValue}>
      {children}
    </AppDrawerContext.Provider>
  )
}

// Hook to use drawer context
export function useDrawerContext() {
  const ctx = React.useContext(AppDrawerContext)
  if (!ctx) throw new Error('useDrawerContext must be used within DrawerProvider')
  return ctx
}

// Capitalize helper
function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1)
}

// Main App component (simplified from 7355 lines)
export function App() {
  // All existing state management from original App.tsx
  // (This will be integrated with your current state management system)

  // Fleet/printer state
  const [fleet, setFleet] = useState<any>(null)
  const [fleetLoading, setFleetLoading] = useState(false)
  const [currentPrinter, setCurrentPrinter] = useState<any>(null)
  const [detailsPrinterId, setDetailsPrinterId] = useState<string | null>(null)

  // Drawer state
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [fleetToolsOpen, setFleetToolsOpen] = useState(false)
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)

  // Auth/UI state
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [canWrite, setCanWrite] = useState(false)
  const [userRole, setUserRole] = useState<string>('')

  // Diagnostics and metrics
  const [diagnostics, setDiagnostics] = useState<any>(null)
  const [currentMetric, setCurrentMetric] = useState<any>(null)
  const [history, setHistory] = useState<any>(null)

  // Modal states
  const [confirmState, setConfirmState] = useState<any>(null)
  const [alphaAckPending, setAlphaAckPending] = useState<{ printer: any; retry: () => void } | null>(null)
  const [setupMode, setSetupMode] = useState(false)

  // Get drawer context
  const { activeSection, setActiveSection, drawerMessage, setDrawerMessage } = useDrawerContext()

  // Initialize app
  useEffect(() => {
    (async () => {
      try {
        await initializeAuth()
        // TODO: fetch user profile from /api/auth/me to get isAuthenticated, canWrite, role
        // For now, auth state is initialized from tokens in localStorage
      } catch (e) {
        error('App', 'Auth initialization failed', e)
      }
    })()
  }, [])

  // Load fleet on mount and set up polling
  useEffect(() => {
    const loadFleet = async () => {
      setFleetLoading(true)
      try {
        const r = await apiFetch('/api/printers')
        if (r.ok) {
          const data = await r.json()
          setFleet(data)
          if (data.printers?.length > 0) {
            const first = data.printers[0]
            setCurrentPrinter(first)
            setDetailsPrinterId(first.id)
          }
        }
      } catch (e) {
        error('App', 'Fleet load failed', e)
      } finally {
        setFleetLoading(false)
      }
    }

    loadFleet()
    const interval = setInterval(loadFleet, 5000)
    return () => clearInterval(interval)
  }, [])

  // Fetch diagnostics for current printer
  useEffect(() => {
    if (!detailsPrinterId) return

    (async () => {
      try {
        const r = await apiFetch(`/api/printers/${detailsPrinterId}/diagnostics`)
        if (r.ok) {
          const d = await r.json()
          setDiagnostics(d)
        }
      } catch (e) {
        debug('App', 'Diagnostics fetch failed', e)
      }
    })()
  }, [detailsPrinterId])

  // Build drawer props based on current state
  const drawerProps: DrawerProps = useMemo(() => {
    // printerId is required; only build props if we have a valid id
    if (!detailsPrinterId) {
      return {
        printerId: '',
        canWrite: false,
      } as DrawerProps
    }

    return {
      printerId: detailsPrinterId,
      printer: currentPrinter,
      currentPrinter,
      diagnostics,
      canWrite,
      currentMetric,
      history,
      userRole,
      onDone: () => {
        // Trigger a refresh of diagnostics after operations
        apiFetch(`/api/printers/${detailsPrinterId}/diagnostics`)
          .then(r => r.ok ? r.json() : null)
          .then(d => { if (d) setDiagnostics(d) })
      },
    }
  }, [detailsPrinterId, currentPrinter, diagnostics, canWrite, currentMetric, history, userRole])

  // Render active drawer (only if we have a printerId)
  const ActiveDrawer = (activeSection && detailsPrinterId) ? DRAWER_COMPONENTS[activeSection] : null

  return (
    <>
      {/* Main layout */}
      <div className="app-layout">
        {/* Top bar with printer selection and tools */}
        <header className="app-header">
          <div className="header-content">
            <h1>MEMAR</h1>
            {currentPrinter && (
              <div className="printer-selector">
                <select
                  value={detailsPrinterId || ''}
                  onChange={(e) => {
                    const id = e.target.value
                    setDetailsPrinterId(id)
                    const p = fleet?.printers?.find((pr: any) => pr.id === id)
                    if (p) setCurrentPrinter(p)
                  }}
                >
                  {fleet?.printers?.map((p: any) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
            )}
            <div className="header-actions">
              <button onClick={() => setFleetToolsOpen(true)}>Fleet Tools</button>
              <button onClick={() => setAddDeviceOpen(true)}>+ Add Device</button>
            </div>
          </div>
        </header>

        {/* Main content area */}
        <div className="app-content">
          {/* Left panel - floor plan / 3D view / etc */}
          <main className="app-main">
            {setupMode && <SetupWizard onClose={() => setSetupMode(false)} isOpen={setupMode} />}
            {!setupMode && currentPrinter && (
              <FloorPlan2D devices={[]} imageUrl={null} editMode={false} />
            )}
          </main>

          {/* Right panel - drawer tabs and content */}
          <aside className="app-drawer">
            {/* Tab bar for drawer selection */}
            <div className="drawer-tabs">
              {DRAWER_NAMES.map(section => (
                <button
                  key={section}
                  className={`drawer-tab ${activeSection === section ? 'active' : ''}`}
                  onClick={() => setActiveSection(section)}
                  aria-current={activeSection === section ? 'page' : undefined}
                >
                  {capitalize(section)}
                </button>
              ))}
            </div>

            {drawerLoading && (
              <div className="drawer-section">
                <div className="subtle">Loading workspace…</div>
              </div>
            )}

            {!drawerLoading && (
              <>
                {/* Message display */}
                {drawerMessage && (
                  <div
                    className={`drawer-message message-${drawerMessage.severity}`}
                    role="status"
                    aria-live="polite"
                    aria-atomic="true"
                  >
                    {drawerMessage.text}
                  </div>
                )}

                {/* Active drawer component */}
                {ActiveDrawer ? (
                  <React.Suspense fallback={
                    <div className="drawer-section">
                      <div className="subtle">Loading…</div>
                    </div>
                  }>
                    <ActiveDrawer {...drawerProps} />
                  </React.Suspense>
                ) : (
                  <div className="drawer-section">
                    <div className="subtle">No drawer selected.</div>
                  </div>
                )}

                {/* Read-only message for restricted sections */}
                {['jog', 'console', 'bedmesh'].includes(activeSection || '') && !canWrite && (
                  <section className="drawer-section">
                    <h3>{capitalize(activeSection || '')}</h3>
                    <div className="subtle">This control requires an operator or admin role. You have read-only access.</div>
                  </section>
                )}
              </>
            )}
          </aside>
        </div>
      </div>

      {/* Fleet tools modal */}
      {fleetToolsOpen && <FleetToolsModal onClose={() => setFleetToolsOpen(false)} canWrite={canWrite} />}

      {/* Add device modal */}
      {addDeviceOpen && (
        <div className="modal-overlay" onClick={() => setAddDeviceOpen(false)}>
          <div className="modal-content" role="dialog" aria-modal="true" aria-label="Add device" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setAddDeviceOpen(false)} aria-label="Close">✕</button>
            <h2>Add device</h2>
            <div className="settings-grid">
              {/* Add device form will go here */}
              <div className="subtle">Add device wizard coming soon.</div>
            </div>
          </div>
        </div>
      )}

      {/* Confirm dialog */}
      {confirmState && (
        <ConfirmDialog
          message={confirmState.message}
          onConfirm={confirmState.onConfirm}
          onCancel={() => setConfirmState(null)}
        />
      )}

      {/* Alpha acknowledge modal */}
      {alphaAckPending && (
        <AlphaAcknowledgeModal
          deviceId={alphaAckPending.printer.id}
          deviceName={alphaAckPending.printer.name}
          protocol={alphaAckPending.printer.protocol || ''}
          onAcknowledged={() => {
            const retry = alphaAckPending.retry
            setAlphaAckPending(null)
            retry()
          }}
          onCancel={() => setAlphaAckPending(null)}
        />
      )}
    </>
  )
}

// Root export with DrawerProvider
export default function AppRoot() {
  return (
    <DrawerProvider>
      <App />
    </DrawerProvider>
  )
}
