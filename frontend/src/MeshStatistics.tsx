/**
 * Mesh statistics panel showing Z-height metrics
 */

import React, { useMemo } from 'react'
import { calculateMeshStats, MeshStats } from './meshUtils'

interface MeshStatisticsProps {
  matrix: number[][]
  minZ: number | null
  maxZ: number | null
  profileName?: string
  isProbed?: boolean
}

export const MeshStatistics: React.FC<MeshStatisticsProps> = ({
  matrix,
  minZ,
  maxZ,
  profileName,
  isProbed,
}) => {
  const stats = useMemo<MeshStats | null>(() => {
    if (!matrix || matrix.length === 0) return null
    try {
      return calculateMeshStats(matrix)
    } catch {
      return null
    }
  }, [matrix])

  if (!stats) {
    return <div className="subtle small">No mesh data available</div>
  }

  const rows = [
    { label: 'Min Z', value: `${stats.minZ.toFixed(3)} mm` },
    { label: 'Max Z', value: `${stats.maxZ.toFixed(3)} mm` },
    { label: 'Avg Z', value: `${stats.avgZ.toFixed(3)} mm` },
    { label: 'Flatness', value: `${stats.flatness.toFixed(3)} mm` },
    { label: 'Grid size', value: `${stats.gridWidth} × ${stats.gridHeight}` },
    { label: 'Total points', value: stats.pointCount.toLocaleString() },
    ...(profileName ? [{ label: 'Profile', value: profileName }] : []),
    ...(isProbed !== undefined ? [{ label: 'Status', value: isProbed ? 'Probed' : 'Interpolated' }] : []),
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="subtle small" style={{ marginBottom: 4 }}>Statistics</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} style={{ borderBottom: 'var(--border-default) 1px solid', paddingBottom: 4 }}>
              <td style={{ paddingRight: 12, paddingBottom: 6, color: 'var(--text-secondary)' }}>
                {row.label}
              </td>
              <td style={{ paddingBottom: 6, fontFamily: 'var(--font-mono)', textAlign: 'right' }}>
                {row.value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
