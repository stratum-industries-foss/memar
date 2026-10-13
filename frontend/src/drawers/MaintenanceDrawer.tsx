import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { MaintenancePanel } from '../FleetTools'

const MaintenanceDrawer = React.memo(function MaintenanceDrawer({ printerId, canWrite, onDone, ...props }: DrawerProps) {
  if (!printerId) return null

  return <MaintenancePanel printerId={printerId} canWrite={canWrite ?? false} onDone={onDone} />
})

export default MaintenanceDrawer
