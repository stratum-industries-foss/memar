/**
 * App Context and Drawer Context
 * Provides centralized state management for drawer UI and printer data
 */

import React from 'react'
import type {
  DrawerContextType,
  DrawerSection,
  DrawerMessage,
  Printer,
  Diagnostics,
} from './types'

// Create the main drawer context
export const AppDrawerContext = React.createContext<DrawerContextType | null>(null)

// Export the context type for external use
export type { DrawerContextType, DrawerSection, DrawerMessage }

/**
 * Hook to access drawer context
 * Provides access to drawer state, printer data, and callbacks
 */
export function useAppDrawer(): DrawerContextType {
  const ctx = React.useContext(AppDrawerContext)
  if (!ctx) {
    throw new Error('useAppDrawer must be used within AppDrawerContext.Provider')
  }
  return ctx
}

/**
 * Alternative hook name for compatibility
 * useDrawerContext is an alias for useAppDrawer
 */
export function useDrawerContext(): DrawerContextType {
  return useAppDrawer()
}

/**
 * Provider component for drawer context
 * Wraps application to provide drawer state to all children
 */
export function DrawerProvider({
  children,
  value,
}: {
  children: React.ReactNode
  value: DrawerContextType
}) {
  return (
    <AppDrawerContext.Provider value={value}>
      {children}
    </AppDrawerContext.Provider>
  )
}
