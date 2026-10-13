import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { CNCMetricsPanel } from '../CNCMetricsPanel'

const CncDrawer = React.memo(function CncDrawer({ printerId, ...props }: DrawerProps) {
  if (!printerId) return null

  return <CNCMetricsPanel deviceId={printerId} />
})

export default CncDrawer
