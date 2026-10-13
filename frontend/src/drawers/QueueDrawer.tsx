import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { QueuePanel } from '../FleetTools'

const QueueDrawer = React.memo(function QueueDrawer({ printerId, canWrite, ...props }: DrawerProps) {
  if (!printerId) return null

  return <QueuePanel printerId={printerId} canWrite={canWrite ?? false} />
})

export default QueueDrawer
