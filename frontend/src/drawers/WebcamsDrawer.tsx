import React, { useState } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useWebcamsState } from './useWebcamsState'

/**
 * WebcamImage component — renders MJPEG stream with snapshot fallback
 *
 * Imported from App.tsx:7288. Uses ticket-based auth for stream access.
 * Handles stream errors with fallback to snapshot polling.
 *
 * @param printerId - Printer ID for API calls
 * @param camUid - Camera UID
 * @param snapTs - Snapshot timestamp for cache-busting
 * @param alt - Image alt text
 */
declare const WebcamImage: React.ComponentType<{
  printerId: string
  camUid: string
  snapTs: number
  alt: string
}>

interface WebcamsDrawerProps extends DrawerProps {
  printerId?: string
}

const WebcamsDrawer = React.memo(function WebcamsDrawer({ printerId }: WebcamsDrawerProps) {
  const {
    cameraList,
    isLoading,
    error,
    selectedCameraUid,
    setSelectedCameraUid,
    layoutMode,
    setLayoutMode,
    streamQuality,
    setStreamQuality,
    isFullscreen,
    setIsFullscreen,
    cameraErrors,
    setCameraError,
    cameraTransforms,
    updateCameraTransform,
  } = useWebcamsState(printerId)

  // Snapshot timestamp for cache-busting
  const [snapTs] = useState(() => Date.now())

  if (!printerId) {
    return (
      <section className="drawer-section">
        <h3>Webcams</h3>
        <div className="subtle">No printer selected</div>
      </section>
    )
  }

  if (isLoading) {
    return (
      <section className="drawer-section">
        <h3>Webcams</h3>
        <div className="subtle">Loading cameras...</div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="drawer-section">
        <h3>Webcams</h3>
        <div className="subtle" style={{ color: 'var(--color-error)' }}>
          {error}
        </div>
      </section>
    )
  }

  if (cameraList.length === 0) {
    return (
      <section className="drawer-section">
        <h3>Webcams</h3>
        <div className="subtle">No webcams reported by Moonraker</div>
      </section>
    )
  }

  // Calculate grid columns based on layout mode
  const gridCols = layoutMode === 1 ? 1 : layoutMode === 2 ? 2 : 4

  return (
    <>
      <section className="drawer-section">
        <h3>Webcams ({cameraList.length})</h3>

        {/* Controls */}
        <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: '0.85rem', whiteSpace: 'nowrap' }}>Layout:</span>
            <select
              value={layoutMode}
              onChange={(e) => setLayoutMode(parseInt(e.target.value, 10) as 1 | 2 | 4)}
              style={{ padding: '2px 4px' }}
            >
              <option value={1}>1 camera</option>
              <option value={2}>2 cameras</option>
              <option value={4}>4 cameras</option>
            </select>
          </label>

          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: '0.85rem', whiteSpace: 'nowrap' }}>Quality:</span>
            <select
              value={streamQuality}
              onChange={(e) => setStreamQuality(e.target.value as 'low' | 'medium' | 'high')}
              style={{ padding: '2px 4px' }}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>

          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            style={{ padding: '2px 8px', fontSize: '0.85rem' }}
          >
            {isFullscreen ? '⎋ Exit' : '⛶ Fullscreen'}
          </button>
        </div>

        {/* Camera grid */}
        <div
          className="webcam-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
            gap: 12,
            marginBottom: 12,
          }}
        >
          {cameraList.map((cam) => {
            const transforms = cameraTransforms[cam.uid] ?? { rotate: 0, flipH: false, flipV: false }
            const transformStyle = `rotate(${transforms.rotate}deg) scaleX(${transforms.flipH ? -1 : 1}) scaleY(${transforms.flipV ? -1 : 1})`

            return (
              <div
                key={cam.uid}
                className={`webcam-card ${selectedCameraUid === cam.uid ? 'selected' : ''}`}
                onClick={() => setSelectedCameraUid(cam.uid)}
                style={{
                  padding: 8,
                  border: selectedCameraUid === cam.uid ? '2px solid var(--accent)' : '1px solid var(--border)',
                  borderRadius: 4,
                  cursor: 'pointer',
                  backgroundColor: 'var(--bg-2)',
                }}
              >
                <div style={{ marginBottom: 6 }}>
                  <strong>{cam.name}</strong>
                  <div className="subtle small">{cam.location || cam.service || 'camera'}</div>
                </div>

                {/* Camera stream/snapshot */}
                <div
                  style={{
                    position: 'relative',
                    width: '100%',
                    aspectRatio: cam.aspect_ratio || '16 / 9',
                    backgroundColor: 'var(--bg-3)',
                    borderRadius: 4,
                    overflow: 'hidden',
                    marginBottom: 6,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <div style={{ transform: transformStyle, width: '100%', height: '100%' }}>
                    <WebcamImage
                      printerId={printerId}
                      camUid={cam.uid}
                      snapTs={snapTs}
                      alt={cam.name}
                    />
                  </div>
                  {cameraErrors[cam.uid] && (
                    <div
                      style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        padding: '4px 6px',
                        color: 'var(--color-error)',
                        fontSize: '0.75rem',
                      }}
                    >
                      {cameraErrors[cam.uid]}
                    </div>
                  )}
                </div>

                {/* Camera controls */}
                <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                  <button
                    onClick={() =>
                      updateCameraTransform(cam.uid, {
                        rotate: (transforms.rotate + 90) % 360,
                      })
                    }
                    title="Rotate 90°"
                    style={{ flex: 1, padding: '2px 4px', fontSize: '0.75rem' }}
                  >
                    ↻ Rotate
                  </button>
                  <button
                    onClick={() =>
                      updateCameraTransform(cam.uid, { flipH: !transforms.flipH })
                    }
                    title="Flip horizontally"
                    style={{ flex: 1, padding: '2px 4px', fontSize: '0.75rem' }}
                  >
                    ↔ Flip H
                  </button>
                  <button
                    onClick={() =>
                      updateCameraTransform(cam.uid, { flipV: !transforms.flipV })
                    }
                    title="Flip vertically"
                    style={{ flex: 1, padding: '2px 4px', fontSize: '0.75rem' }}
                  >
                    ↕ Flip V
                  </button>
                </div>

                {/* Connection status */}
                <div className="subtle small" style={{ textAlign: 'center' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      backgroundColor: cam.enabled
                        ? 'var(--color-success)'
                        : 'var(--color-warning)',
                      marginRight: 4,
                    }}
                  />
                  {cam.enabled ? 'Online' : 'Disabled'}
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </>
  )
})

export default WebcamsDrawer

