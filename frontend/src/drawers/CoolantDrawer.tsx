import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { CoolantMetricsPanel } from '../CoolantMetricsPanel'

const CoolantDrawer = React.memo(function CoolantDrawer({ printerId, ...props }: DrawerProps) {
  if (!printerId) return null

  return <CoolantMetricsPanel deviceId={printerId} />
})

export default CoolantDrawer
