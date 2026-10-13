import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { HealthPanel } from '../FleetTools'

const HealthDrawer = React.memo(function HealthDrawer({ printerId, ...props }: DrawerProps) {
  if (!printerId) return null

  return <HealthPanel printerId={printerId} />
})

export default HealthDrawer
