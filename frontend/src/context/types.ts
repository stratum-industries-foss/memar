/**
 * Context and component interface types
 * Extracted from App.tsx for reusability
 */

import type { Printer } from '../types/printer'
import type { DrawerProps } from '../types/drawer-props'

// Re-export Printer from types
export type { Printer }

// Re-export DrawerProps from canonical location
export type { DrawerProps }

// Diagnostics type
export type Diagnostics = {
  [key: string]: any
}

// Drawer message type
export type DrawerMessage = {
  level: 'info' | 'warn' | 'error'
  title?: string
  message: string
  delay?: number
}

// Drawer sections — aligned with App.tsx DRAWER_COMPONENTS registry
export type DrawerSection =
  | 'overview'
  | 'temperature'
  | 'jog'
  | 'macros'
  | 'files'
  | 'history'
  | 'webcams'
  | 'timelapse'
  | 'dryrun'
  | 'settings'
  | 'console'
  | 'bedmesh'
  | 'queue'
  | 'maintenance'
  | 'health'
  | 'cnc'
  | 'coolant'
  | 'analytics'
  | 'system-settings'

// Drawer context type
export type DrawerContextType = {
  activeSection: DrawerSection | null
  setActiveSection: (section: DrawerSection | null) => void
  drawerMessage: DrawerMessage
  setDrawerMessage: (msg: DrawerMessage) => void
  printerId: string
  currentPrinter: Printer | null
  macros: any[]
  canWrite: boolean
  searchTerm: string
  setSearchTerm: (term: string) => void
  startPrint: (printerId: string, filename: string) => Promise<void>
  showToast: (message: string, level?: string) => void
}
