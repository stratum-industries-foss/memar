import React, { useRef, useState, useCallback } from 'react'

export interface DevicePosition {
  device_id: string
  x: number
  y: number
  rotation: number
  status?: 'printing' | 'error' | 'paused' | 'idle' | 'offline'
  label?: string
  metric?: string
  type?: string
}

interface FloorPlan2DProps {
  devices: DevicePosition[]
  imageUrl: string | null
  editMode: boolean
  onLayoutUpdate?: (devices: DevicePosition[]) => void
  autoScale?: boolean
  selectedIds?: string[]
  onDeviceClick?: (deviceId: string) => void
}

interface DragState {
  deviceId: string
  startX: number
  startY: number
  offsetX: number
  offsetY: number
}

interface ScaleInfo {
  scale: number
  offsetX: number
  offsetY: number
}

const statusColorMap: Record<string, string> = {
  printing: 'var(--color-success)',
  error: 'var(--color-danger)',
  paused: 'var(--color-warning)',
  idle: 'var(--color-info)',
  // Use an opaque neutral for offline tiles. --text-disabled is rgba(...,0.38)
  // which composites to ~rgb(118,118,123) on the dark surface — white text on
  // that gives ≈3.1:1, failing WCAG AA (4.5:1). #4a4a52 gives ≥5:1 with #fff.
  offline: '#4a4a52',
}

const GRID_SIZE = 10  // Grid snapping: 10px
const DEVICE_SIZE = 60  // Device box size in pixels

export const FloorPlan2D: React.FC<FloorPlan2DProps> = ({
  devices,
  imageUrl,
  editMode,
  onLayoutUpdate,
  autoScale = true,
  selectedIds = [],
  onDeviceClick,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [localDevices, setLocalDevices] = useState(devices)
  const [scaleInfo, setScaleInfo] = useState<ScaleInfo>({ scale: 1, offsetX: 0, offsetY: 0 })

  React.useEffect(() => {
    if (!dragState) setLocalDevices(devices)
  }, [devices, dragState])

  // HIGH-FE-05: when a floor-plan image is present, device (x, y) are pixel
  // coordinates on that image's ORIGINAL (natural) dimensions. To register
  // devices consistently against the image in both view and edit mode, we
  // need a single shared transform derived from where the image actually
  // renders under `background-size: contain` — not two independently-fitted,
  // device-only transforms (the old viewBounds/scaleInfo split), which have
  // no relationship to the image's on-screen rectangle at all.
  const [imageNatural, setImageNatural] = useState<{ w: number; h: number } | null>(null)
  const [containerSize, setContainerSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 })

  React.useEffect(() => {
    if (!imageUrl) {
      setImageNatural(null)
      return
    }
    let cancelled = false
    const img = new window.Image()
    img.onload = () => {
      if (!cancelled) setImageNatural({ w: img.naturalWidth, h: img.naturalHeight })
    }
    img.onerror = () => {
      if (!cancelled) setImageNatural(null)
    }
    img.src = imageUrl
    return () => { cancelled = true }
  }, [imageUrl])

  React.useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        setContainerSize({
          w: containerRef.current.clientWidth,
          h: containerRef.current.clientHeight,
        })
      }
    }
    const id = requestAnimationFrame(measure)
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(id)
      window.removeEventListener('resize', measure)
    }
    // Re-measure whenever mode or content that affects container size changes.
  }, [editMode, imageUrl, devices.length])

  // The image's rendered (contain-fit) rectangle within the current container,
  // replicating CSS `background-size: contain; background-position: center`.
  // Only meaningful once we know both the image's natural size and the
  // container's current measured size.
  const imageRect = React.useMemo(() => {
    if (!imageUrl || !imageNatural || containerSize.w === 0 || containerSize.h === 0) {
      return null
    }
    const scale = Math.min(
      containerSize.w / imageNatural.w,
      containerSize.h / imageNatural.h,
    )
    const renderedW = imageNatural.w * scale
    const renderedH = imageNatural.h * scale
    return {
      scale,
      offsetX: (containerSize.w - renderedW) / 2,
      offsetY: (containerSize.h - renderedH) / 2,
    }
  }, [imageUrl, imageNatural, containerSize])

  // View-mode bounds: size the container to exactly fit all devices, adaptively.
  //
  // Geometry facts this must respect (see render below + styles.css):
  //  - Each box is drawn with `left/top = (x + offset) * scale` then
  //    `translate(-50%,-50%)`, so (device.x, device.y) is the box CENTER.
  //  - `.floorplan-device` is a HARD 60px box (DEVICE_SIZE). `scale` only
  //    scales the center *positions*, never the boxes. So if scale drops
  //    below DEVICE_SIZE / grid_pitch, fixed-size boxes overlap even while
  //    their centers still fit. That is the "compresses too much" bug.
  const viewBounds = React.useMemo(() => {
    if (devices.length === 0) return { offsetX: 0, offsetY: 0, scale: 1, w: 200, h: 120 }

    const HALF = DEVICE_SIZE / 2 // 30 — a box extends this far from its center
    const MARGIN = 8             // breathing room between box edge and container edge
    const maxViewH = 200         // preferred cap on rendered height

    // Bounds of the device CENTERS (not edges — the box half is added later).
    const minX = Math.min(...devices.map(d => d.x))
    const maxX = Math.max(...devices.map(d => d.x))
    const minY = Math.min(...devices.map(d => d.y))
    const maxY = Math.max(...devices.map(d => d.y))
    const spanX = maxX - minX // center-to-center extent
    const spanY = maxY - minY

    // Overlap floor: for every pair, the larger of |dx|/|dy| (Chebyshev
    // distance) times scale must stay >= DEVICE_SIZE, or the fixed 60px boxes
    // collide. The tightest pair sets the minimum scale we may use.
    let minPitch = Infinity
    for (let i = 0; i < devices.length; i++) {
      for (let j = i + 1; j < devices.length; j++) {
        const cheb = Math.max(
          Math.abs(devices[i].x - devices[j].x),
          Math.abs(devices[i].y - devices[j].y),
        )
        if (cheb > 0) minPitch = Math.min(minPitch, cheb)
      }
    }
    // Below this scale, boxes overlap. Capped at 1 (can't over-inflate).
    const overlapFloor = Number.isFinite(minPitch) ? Math.min(1, DEVICE_SIZE / minPitch) : 0

    // Scale that would make rendered height meet maxViewH exactly. The vertical
    // budget for scaled centers is (maxViewH - full box - both margins).
    const heightBudget = maxViewH - DEVICE_SIZE - MARGIN * 2
    const fitScale = spanY > 0 ? heightBudget / spanY : 1

    // Fit to height, but never compress past the overlap floor. Clamp to <= 1.
    const scale = Math.min(1, Math.max(overlapFloor, Math.min(1, fitScale)))

    // Place the top-left-most center at (MARGIN + HALF) so its box edge sits
    // exactly MARGIN inside the container — guarantees no edge cutoff.
    // Render computes center = (x + offset) * scale, so solve for offset.
    return {
      offsetX: (MARGIN + HALF) / scale - minX,
      offsetY: (MARGIN + HALF) / scale - minY,
      scale,
      // Container = scaled center-span + one full box (half on each end) + margins.
      w: Math.round(spanX * scale + DEVICE_SIZE + MARGIN * 2),
      h: Math.round(spanY * scale + DEVICE_SIZE + MARGIN * 2),
    }
  }, [devices])

  // Calculate scale to fit all devices in container (edit mode only)
  React.useEffect(() => {
    if (!autoScale || !editMode || devices.length === 0) {
      if (!editMode) setScaleInfo({ scale: 1, offsetX: 0, offsetY: 0 })
      return
    }

    const compute = () => {
      const padding = 10
      const deviceSize = 60
      const minX = Math.min(...devices.map(d => d.x))
      const maxX = Math.max(...devices.map(d => d.x + deviceSize))
      const minY = Math.min(...devices.map(d => d.y))
      const maxY = Math.max(...devices.map(d => d.y + deviceSize))

      const contentWidth = maxX - minX
      const contentHeight = maxY - minY

      if (containerRef.current) {
        const container = containerRef.current
        const availableWidth = container.clientWidth - padding * 2
        const availableHeight = container.clientHeight - padding * 2

        if (contentWidth > 0 && contentHeight > 0 && availableWidth > 0 && availableHeight > 0) {
          const scaleX = availableWidth / contentWidth
          const scaleY = availableHeight / contentHeight
          const scale = Math.min(scaleX, scaleY, 1)

          setScaleInfo({
            scale,
            offsetX: -minX + padding / scale,
            offsetY: -minY + padding / scale,
          })
        }
      }
    }

    // rAF ensures CSS has applied and container has measured dimensions
    const id = requestAnimationFrame(compute)
    return () => cancelAnimationFrame(id)
  }, [devices, autoScale, editMode])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>, deviceId: string) => {
      if (!editMode) return
      e.preventDefault()

      const device = localDevices.find(d => d.device_id === deviceId)
      if (!device) return

      setDragState({
        deviceId,
        startX: e.clientX,
        startY: e.clientY,
        offsetX: device.x,
        offsetY: device.y,
      })
    },
    [editMode, localDevices]
  )

  const checkCollision = useCallback(
    (newX: number, newY: number, excludeDeviceId: string): boolean => {
      return localDevices.some(d => {
        if (d.device_id === excludeDeviceId) return false
        const dx = Math.abs(d.x - newX)
        const dy = Math.abs(d.y - newY)
        return dx < DEVICE_SIZE && dy < DEVICE_SIZE
      })
    },
    [localDevices]
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!dragState) return

      // Device coordinates are rendered scaled by the active transform (the
      // shared imageRect transform when a floor-plan image is registered,
      // otherwise scaleInfo in edit mode). Convert the raw screen-pixel delta
      // back into device coordinates by dividing by that same scale, otherwise
      // the device lags the cursor whenever the plan is zoomed out (scale < 1).
      const scale = (imageRect ? imageRect.scale : scaleInfo.scale) || 1
      const deltaX = (e.clientX - dragState.startX) / scale
      const deltaY = (e.clientY - dragState.startY) / scale

      let newX = Math.max(0, dragState.offsetX + deltaX)
      let newY = Math.max(0, dragState.offsetY + deltaY)

      // Snap to grid
      newX = Math.round(newX / GRID_SIZE) * GRID_SIZE
      newY = Math.round(newY / GRID_SIZE) * GRID_SIZE

      // Prevent overlap with other devices
      if (checkCollision(newX, newY, dragState.deviceId)) {
        return
      }

      setLocalDevices(prev =>
        prev.map(d =>
          d.device_id === dragState.deviceId
            ? { ...d, x: newX, y: newY }
            : d
        )
      )
    },
    [dragState, checkCollision, scaleInfo, imageRect]
  )

  const handleMouseUp = useCallback(() => {
    if (dragState && onLayoutUpdate) {
      onLayoutUpdate(localDevices)
    }
    setDragState(null)
  }, [dragState, localDevices, onLayoutUpdate])

  return (
    <div
      ref={containerRef}
      className="floorplan-container"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{
        backgroundImage: imageUrl ? `url(${imageUrl})` : undefined,
        // View mode always sets an explicit inline size (viewBounds), image or
        // not: the surrounding widget CSS (.floorplan-widget-section
        // .floorplan-container { height: auto }) depends on the component
        // supplying a real height here, and every child is position:absolute
        // (zero auto-height contribution) — without this, the widget
        // collapses to ~0px in view mode whenever an image is registered.
        // This is orthogonal to HIGH-FE-05: the registration bug was that
        // device POSITION used two unrelated formulas across modes, not that
        // the container's pixel size must match between modes. imageRect is
        // measured from whatever containerSize actually renders (via
        // clientWidth/clientHeight), so devices stay correctly registered to
        // the image inside this box regardless of the box's absolute size.
        ...(!editMode ? { width: `${viewBounds.w}px`, height: `${viewBounds.h}px` } : {}),
      }}
    >
      {localDevices.map(device => {
        const color = statusColorMap[device.status || 'offline']
        const isSelected = selectedIds.includes(device.device_id)
        let scaledX: number
        let scaledY: number
        if (imageRect) {
          // Device (x, y) are pixel coordinates on the image's natural
          // dimensions; imageRect is the SAME transform in both modes.
          scaledX = imageRect.offsetX + device.x * imageRect.scale
          scaledY = imageRect.offsetY + device.y * imageRect.scale
        } else {
          const info = editMode ? scaleInfo : viewBounds
          scaledX = (device.x + info.offsetX) * info.scale
          scaledY = (device.y + info.offsetY) * info.scale
        }

        const typeIcon = device.type === 'sla' ? '◈' : device.type === 'idex' ? '⊕' : null
        return (
          <div
            key={device.device_id}
            className={[
              'floorplan-device',
              isSelected ? 'selected' : '',
              device.status === 'printing' ? 'fp-printing' : '',
            ].filter(Boolean).join(' ')}
            style={{
              left: `${scaledX}px`,
              top: `${scaledY}px`,
              transform: `translate(-50%, -50%) rotate(${device.rotation}deg)`,
              backgroundColor: color,
              cursor: editMode ? 'grab' : 'pointer',
            }}
            onMouseDown={e => handleMouseDown(e, device.device_id)}
            onClick={() => { if (!editMode) onDeviceClick?.(device.device_id) }}
            role="button"
            tabIndex={0}
            aria-label={device.label || device.device_id}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                if (!editMode) onDeviceClick?.(device.device_id)
              }
            }}
          >
            <div className="device-inner">
              {device.label && <span className="device-label">{device.label}</span>}
              {device.metric && <span className="device-metric">{device.metric}</span>}
            </div>
            {typeIcon && <span className="fp-type-icon">{typeIcon}</span>}
          </div>
        )
      })}
    </div>
  )
}
