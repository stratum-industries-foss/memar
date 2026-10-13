import React, { useMemo, useState } from 'react'
import BedMeshVisualizer from './BedMeshVisualizer'
import { MeshStatistics } from './MeshStatistics'
import { MeshControls } from './MeshControls'

type ViewMode = '2d' | '3d'
type RenderMode = 'solid' | 'wireframe' | 'transparent'

interface BedMeshData {
  supported: boolean
  active_profile?: string
  active_is_probed?: boolean
  profiles?: Array<{
    name: string
    points?: Array<[number, number]>
    mesh_params?: Record<string, any>
    mesh_matrix?: number[][]
    probed_points?: number
    min_z?: number | null
    max_z?: number | null
  }>
  mesh_matrix?: number[][]
  x_count?: number
  y_count?: number
  global_min_z?: number | null
  global_max_z?: number | null
  mesh_extent?: {
    x_min: number | null
    x_max: number | null
    y_min: number | null
    y_max: number | null
  }
}

interface HeatmapRendererProps {
  matrix: number[][]
  minZ: number | null
  maxZ: number | null
  title?: string
  width?: number
  height?: number
}

const HeatmapRenderer: React.FC<HeatmapRendererProps> = ({ matrix, minZ, maxZ, title, width = 300, height = 300 }) => {
  if (!matrix || matrix.length === 0) {
    return <div className="subtle small">No mesh data</div>
  }

  // Normalize to [0, 1] using provided global scale
  const normalizeZ = (z: number | null) => {
    if (z === null) return 0.5
    if (minZ === null || maxZ === null) return 0.5
    if (minZ === maxZ) return 0.5
    return (z - minZ) / (maxZ - minZ)
  }

  // Color gradient: blue (low) → green (mid) → red (high)
  const getColor = (normalized: number) => {
    if (normalized < 0.5) {
      const t = normalized * 2
      return `rgb(${Math.round(t * 255)}, ${Math.round(80 + t * 100)}, 255)`
    } else {
      const t = (normalized - 0.5) * 2
      return `rgb(255, ${Math.round(180 - t * 100)}, ${Math.round(255 - t * 255)})`
    }
  }

  const yCount = matrix.length
  const xCount = matrix[0]?.length || 0

  // Responsive sizing based on viewport
  const responsiveWidth = typeof window !== 'undefined' && window.innerWidth < 480 ? Math.min(width, window.innerWidth - 40) : width
  const responsiveHeight = typeof window !== 'undefined' && window.innerWidth < 480 ? Math.min(height, window.innerWidth - 40) : height
  const cellWidth = responsiveWidth / xCount
  const cellHeight = responsiveHeight / yCount

  return (
    <div style={{ marginBottom: 12, overflowX: 'auto' }}>
      {title && <div className="subtle small" style={{ marginBottom: 4 }}>{title}</div>}
      <svg width={responsiveWidth + 40} height={responsiveHeight + 40} style={{ border: '1px solid var(--border)', borderRadius: 4 }}>
        <g transform="translate(20, 20)">
          {matrix.map((row, y) =>
            row.map((z, x) => {
              const norm = normalizeZ(z)
              return (
                <rect
                  key={`${x}-${y}`}
                  x={x * cellWidth}
                  y={y * cellHeight}
                  width={cellWidth}
                  height={cellHeight}
                  fill={getColor(norm)}
                  stroke="rgba(0,0,0,0.1)"
                  strokeWidth="0.5"
                />
              )
            })
          )}
        </g>
      </svg>
      <div className="subtle small" style={{ marginTop: 4 }}>
        Z: {minZ?.toFixed(2) || '—'} to {maxZ?.toFixed(2) || '—'} mm
      </div>
    </div>
  )
}

interface BedMeshPanelProps {
  data: BedMeshData
  onCalibrate?: () => Promise<void>
  isCalibrating?: boolean
  onReload?: () => void
}

export const BedMeshPanel: React.FC<BedMeshPanelProps> = ({
  data,
  onCalibrate,
  isCalibrating = false,
  onReload,
}) => {
  const [viewMode, setViewMode] = useState<ViewMode>('2d')
  const [renderMode, setRenderMode] = useState<RenderMode>('solid')
  const [selectedProfile, setSelectedProfile] = useState<string>(data.active_profile || '')
  const [compareMode, setCompareMode] = useState<'single' | 'side-by-side'>('single')

  if (!data.supported) {
    return <div className="subtle">Bed mesh not supported for this device.</div>
  }

  const profiles = data.profiles || []
  const activeMatrix = data.mesh_matrix || []
  const globalMinZ = data.global_min_z ?? 0
  const globalMaxZ = data.global_max_z ?? 1

  // Get currently displayed matrix based on selected profile
  const displayMatrix = useMemo(() => {
    if (selectedProfile === data.active_profile) {
      return activeMatrix
    }
    const profile = profiles.find((p) => p.name === selectedProfile)
    return profile?.mesh_matrix || activeMatrix
  }, [selectedProfile, activeMatrix, profiles, data.active_profile])

  const profileOptions = profiles.map((p) => ({
    name: p.name,
    isActive: p.name === data.active_profile,
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%' }}>
      {/* Main viewport */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          backgroundColor: 'var(--surface-base)',
          borderRadius: 'var(--radius)',
          border: '1px solid var(--border-default)',
          overflow: 'hidden',
        }}
      >
        {viewMode === '2d' ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, overflow: 'auto' }}>
            <HeatmapRenderer
              matrix={displayMatrix}
              minZ={globalMinZ}
              maxZ={globalMaxZ}
              title={`${selectedProfile || data.active_profile} (${data.active_is_probed ? 'probed' : 'interpolated'})`}
              width={400}
              height={400}
            />
          </div>
        ) : (
          <BedMeshVisualizer
            matrix={displayMatrix}
            minZ={globalMinZ}
            maxZ={globalMaxZ}
            extent={data.mesh_extent}
            renderMode={renderMode}
          />
        )}
      </div>

      {/* Bottom panel: controls + stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Controls */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <MeshControls
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            renderMode={renderMode}
            onRenderModeChange={setRenderMode}
            selectedProfile={selectedProfile}
            profiles={profileOptions}
            onProfileChange={setSelectedProfile}
            onRefresh={onReload}
            onCalibrate={onCalibrate}
            isCalibrating={isCalibrating}
            canCalibrate={true}
          />
        </div>

        {/* Statistics */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <MeshStatistics
            matrix={displayMatrix}
            minZ={globalMinZ}
            maxZ={globalMaxZ}
            profileName={selectedProfile}
            isProbed={selectedProfile === data.active_profile ? data.active_is_probed : undefined}
          />
        </div>
      </div>

      {/* Comparison mode selector (if multiple profiles) */}
      {profiles.length > 1 && (
        <div style={{ paddingTop: 8, borderTop: '1px solid var(--border-default)' }}>
          <label style={{ display: 'block', marginBottom: 8 }}>
            <span className="subtle small">Comparison</span>
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['single', 'side-by-side'] as const).map((mode) => (
              <label key={mode} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="compare-mode"
                  value={mode}
                  checked={compareMode === mode}
                  onChange={() => setCompareMode(mode)}
                />
                <span className="subtle small">{mode === 'side-by-side' ? 'Side-by-side view' : 'Single view'}</span>
              </label>
            ))}
          </div>

          {compareMode === 'side-by-side' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
              <div>
                <div className="subtle small" style={{ marginBottom: 8 }}>Active</div>
                <HeatmapRenderer
                  matrix={activeMatrix}
                  minZ={globalMinZ}
                  maxZ={globalMaxZ}
                  width={200}
                  height={200}
                />
              </div>
              {profiles.slice(0, 1).map((p) => (
                <div key={p.name}>
                  <div className="subtle small" style={{ marginBottom: 8 }}>{p.name}</div>
                  <HeatmapRenderer
                    matrix={p.mesh_matrix || []}
                    minZ={globalMinZ}
                    maxZ={globalMaxZ}
                    width={200}
                    height={200}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
