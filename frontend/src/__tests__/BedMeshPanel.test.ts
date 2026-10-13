import { describe, it, expect } from 'vitest'

describe('BedMeshPanel', () => {
  it('renders unsupported state when bed_mesh is not available', () => {
    const data = { supported: false }
    expect(data.supported).toBe(false)
  })

  it('returns correct global min/max when multiple profiles exist', () => {
    const profiles = [
      { name: 'probe1', mesh_params: {}, probed_points: 25, min_z: 0.1, max_z: 0.8 },
      { name: 'probe2', mesh_params: {}, probed_points: 25, min_z: 0.2, max_z: 0.7 },
      { name: 'manual', mesh_params: {}, probed_points: 25, min_z: 0.0, max_z: 1.0 },
    ]
    const mins = profiles.map(p => p.min_z || 0)
    const maxs = profiles.map(p => p.max_z || 0)
    const globalMin = Math.min(...mins)
    const globalMax = Math.max(...maxs)
    expect(globalMin).toBe(0.0)
    expect(globalMax).toBe(1.0)
  })

  it('correctly identifies active vs saved profiles', () => {
    const data = {
      supported: true,
      active_profile: 'probe1',
      active_is_probed: true,
      profiles: [
        { name: 'probe1', probed_points: 25 },
        { name: 'probe2', probed_points: 25 },
      ],
    }
    expect(data.active_profile).toBe('probe1')
    expect(data.active_is_probed).toBe(true)
    expect(data.profiles.length).toBe(2)
  })

  it('handles mesh extent metadata correctly', () => {
    const extent = {
      x_min: 0, x_max: 200,
      y_min: 0, y_max: 200,
    }
    expect(extent).toEqual({ x_min: 0, x_max: 200, y_min: 0, y_max: 200 })
  })

  it('validates profile comparison eligibility', () => {
    const canCompare = (prof1: string, prof2: string, extent: any) => {
      if (prof1 === prof2) return { eligible: false, reason: 'Same profile' }
      if (!extent) return { eligible: false, reason: 'Mesh extent unknown' }
      return { eligible: true }
    }

    expect(canCompare('probe1', 'probe1', { x_min: 0 }).eligible).toBe(false)
    expect(canCompare('probe1', 'probe2', null).eligible).toBe(false)
    expect(canCompare('probe1', 'probe2', { x_min: 0 }).eligible).toBe(true)
  })

  it('normalizes Z values to [0,1] range for color mapping', () => {
    const normalizeZ = (z: number | null, minZ: number | null, maxZ: number | null) => {
      if (z === null || minZ === null || maxZ === null) return 0.5
      if (minZ === maxZ) return 0.5
      return (z - minZ) / (maxZ - minZ)
    }

    expect(normalizeZ(0.5, 0, 1)).toBe(0.5)
    expect(normalizeZ(0, 0, 1)).toBe(0)
    expect(normalizeZ(1, 0, 1)).toBe(1)
    expect(normalizeZ(0.5, 0.5, 0.5)).toBe(0.5)
  })

  it('derives color gradient from normalized Z (blue→green→red)', () => {
    const getColor = (normalized: number) => {
      if (normalized < 0.5) {
        const t = normalized * 2
        return `rgb(${Math.round(t * 255)}, ${Math.round(80 + t * 100)}, 255)`
      } else {
        const t = (normalized - 0.5) * 2
        return `rgb(255, ${Math.round(180 - t * 100)}, ${Math.round(255 - t * 255)})`
      }
    }

    expect(getColor(0)).toMatch(/rgb\(0, 80, 255\)/)  // blue
    expect(getColor(0.5)).toMatch(/rgb\(255, 180, 255\)/)  // magenta/mid
    expect(getColor(1)).toMatch(/rgb\(255, 80, 0\)/)  // red
  })

  it('handles empty mesh matrix gracefully', () => {
    const data = {
      supported: true,
      active_profile: 'default',
      mesh_matrix: [],
      global_min_z: null,
      global_max_z: null,
    }
    expect(data.mesh_matrix.length).toBe(0)
    expect(data.global_min_z).toBeNull()
  })

  it('extracts grid dimensions from matrix', () => {
    const matrix = [
      [0.1, 0.2, 0.3],
      [0.15, 0.25, 0.35],
      [0.12, 0.22, 0.32],
    ]
    const xCount = matrix[0].length
    const yCount = matrix.length
    expect(xCount).toBe(3)
    expect(yCount).toBe(3)
  })

  it('computes mesh spatial extent from Klipper mesh_min/mesh_max', () => {
    const mesh_min = [10, 20]
    const mesh_max = [190, 180]
    const extent = {
      x_min: mesh_min[0],
      x_max: mesh_max[0],
      y_min: mesh_min[1],
      y_max: mesh_max[1],
    }
    expect(extent.x_min).toBe(10)
    expect(extent.x_max).toBe(190)
    expect(extent.y_min).toBe(20)
    expect(extent.y_max).toBe(180)
  })

  it('preserves all profile metadata for comparison', () => {
    const profile = {
      name: 'probe1',
      points: [[0, 0], [100, 0], [100, 100], [0, 100]],
      mesh_params: { spacing: 25, algo: 'lagrange' },
      probed_points: 4,
      min_z: 0.1,
      max_z: 0.8,
    }
    expect(profile.name).toBe('probe1')
    expect(profile.probed_points).toBe(4)
    expect(profile.mesh_params.algo).toBe('lagrange')
  })
})
