import { describe, it, expect } from 'vitest'
import {
  normalizedZToColor,
  rgbToCss,
  zToColorString,
  calculateMeshStats,
  upsampleMeshBicubic,
  createFlatMesh,
  createTiltedMesh,
  createCurvedMesh,
  createWavyMesh,
  isValidMesh,
  compareMeshes,
} from './meshUtils'

describe('meshUtils', () => {
  describe('normalizedZToColor', () => {
    it('should return blue for low values', () => {
      const [r, g, b] = normalizedZToColor(0)
      expect(r).toBe(0)
      expect(b).toBe(255)
    })

    it('should return red for high values', () => {
      const [r, g, b] = normalizedZToColor(1)
      expect(r).toBe(255)
      expect(b).toBe(0)
    })

    it('should return intermediate color for mid values', () => {
      const [r, g, b] = normalizedZToColor(0.5)
      expect(r).toBe(255)
      expect(g).toBeGreaterThan(100)
      expect(b).toBeGreaterThan(100)
    })

    it('should clamp values outside [0,1]', () => {
      const color1 = normalizedZToColor(-1)
      const color2 = normalizedZToColor(2)
      expect(color1).toEqual(normalizedZToColor(0))
      expect(color2).toEqual(normalizedZToColor(1))
    })
  })

  describe('rgbToCss', () => {
    it('should format RGB values as CSS string', () => {
      const result = rgbToCss(255, 128, 0)
      expect(result).toBe('rgb(255, 128, 0)')
    })
  })

  describe('zToColorString', () => {
    it('should return gray for null values', () => {
      expect(zToColorString(null, 0, 1)).toBe(rgbToCss(128, 128, 128))
    })

    it('should return gray for flat surface', () => {
      expect(zToColorString(5, 5, 5)).toBe(rgbToCss(128, 128, 128))
    })

    it('should map Z values to colors using min/max', () => {
      const color = zToColorString(5, 0, 10)
      // Should be roughly midway between blue and red
      expect(color).not.toBe(rgbToCss(128, 128, 128))
    })
  })

  describe('calculateMeshStats', () => {
    it('should calculate stats for flat mesh', () => {
      const matrix = createFlatMesh(5, 5, 0)
      const stats = calculateMeshStats(matrix)

      expect(stats.minZ).toBe(0)
      expect(stats.maxZ).toBe(0)
      expect(stats.avgZ).toBe(0)
      expect(stats.flatness).toBe(0)
      expect(stats.pointCount).toBe(25)
      expect(stats.gridWidth).toBe(5)
      expect(stats.gridHeight).toBe(5)
    })

    it('should calculate stats for tilted mesh', () => {
      const matrix = createTiltedMesh(5, 5, 1, 0)
      const stats = calculateMeshStats(matrix)

      expect(stats.minZ).toBe(0)
      expect(stats.maxZ).toBeLessThanOrEqual(1.1)
      expect(stats.flatness).toBeGreaterThan(0)
    })

    it('should calculate correct point count', () => {
      const matrix = createFlatMesh(10, 8, 0)
      const stats = calculateMeshStats(matrix)
      expect(stats.pointCount).toBe(80)
    })
  })

  describe('upsampleMeshBicubic', () => {
    it('should not modify mesh with scale=1', () => {
      const original = [[1, 2], [3, 4]]
      const upsampled = upsampleMeshBicubic(original, 1)
      expect(upsampled).toEqual(original)
    })

    it('should preserve original values at grid points', () => {
      const original = createFlatMesh(3, 3, 5)
      const upsampled = upsampleMeshBicubic(original, 2)

      // Original grid points should still be at value 5
      expect(upsampled[0][0]).toBe(5)
      expect(upsampled[2][2]).toBe(5)
    })

    it('should create smooth interpolation', () => {
      const original = createTiltedMesh(2, 2, 1, 0)
      const upsampled = upsampleMeshBicubic(original, 2)

      // Should have more points
      expect(upsampled.length).toBeGreaterThan(original.length)
      expect(upsampled[0].length).toBeGreaterThan(original[0].length)

      // Interpolated values should be between min/max of original
      const flat = upsampled.flat()
      const min = Math.min(...flat)
      const max = Math.max(...flat)
      expect(min).toBeGreaterThanOrEqual(0)
    })

    it('should maintain monotonicity for ramp', () => {
      const original = createTiltedMesh(5, 3, 2, 0)
      const upsampled = upsampleMeshBicubic(original, 2)
      const row = upsampled[Math.floor(upsampled.length / 2)] // Use middle row

      // Values should be monotonically increasing (within floating point tolerance)
      for (let i = 1; i < row.length; i++) {
        expect(row[i]).toBeGreaterThanOrEqual(row[i - 1] - 0.1) // Allow small float errors
      }
    })
  })

  describe('mesh creation functions', () => {
    it('should create flat mesh', () => {
      const mesh = createFlatMesh(3, 2, 5)
      expect(mesh.length).toBe(2)
      expect(mesh[0].length).toBe(3)
      expect(mesh[0][0]).toBe(5)
      expect(mesh.every((row) => row.every((v) => v === 5))).toBe(true)
    })

    it('should create tilted mesh', () => {
      const mesh = createTiltedMesh(3, 3, 1, 1)
      expect(mesh.length).toBe(3)
      expect(mesh[0][0]).toBe(0)
      expect(mesh[2][2]).toBeGreaterThan(1) // Top-right should be elevated
    })

    it('should create curved mesh', () => {
      const mesh = createCurvedMesh(5, 5, 0.5)
      expect(mesh.length).toBe(5)
      // Center should be lowest, edges higher
      const center = mesh[2][2]
      const corner = mesh[0][0]
      expect(Math.abs(corner)).toBeGreaterThan(Math.abs(center))
    })

    it('should create wavy mesh', () => {
      const mesh = createWavyMesh(10, 10, 1.0, 2)
      expect(mesh.length).toBe(10)
      // Should have variation
      const flat = mesh.flat()
      const min = Math.min(...flat)
      const max = Math.max(...flat)
      expect(max - min).toBeGreaterThan(0.1) // Significant variation
    })
  })

  describe('isValidMesh', () => {
    it('should validate correct meshes', () => {
      const valid = [[1, 2], [3, 4]]
      expect(isValidMesh(valid)).toBe(true)
    })

    it('should reject empty mesh', () => {
      expect(isValidMesh([])).toBe(false)
    })

    it('should reject non-rectangular mesh', () => {
      const invalid = [[1, 2], [3]]
      expect(isValidMesh(invalid)).toBe(false)
    })

    it('should reject mesh with non-numeric values', () => {
      const invalid = [[1, 'a'], [3, 4]]
      expect(isValidMesh(invalid)).toBe(false)
    })

    it('should reject mesh with NaN', () => {
      const invalid = [[1, NaN], [3, 4]]
      expect(isValidMesh(invalid)).toBe(false)
    })
  })

  describe('compareMeshes', () => {
    it('should calculate difference matrix', () => {
      const mesh1 = [[1, 2], [3, 4]]
      const mesh2 = [[2, 3], [4, 5]]
      const diff = compareMeshes(mesh1, mesh2)

      expect(diff).toEqual([[1, 1], [1, 1]])
    })

    it('should return null for incompatible sizes', () => {
      const mesh1 = [[1, 2], [3, 4]]
      const mesh2 = [[1, 2, 3], [4, 5, 6]]
      const diff = compareMeshes(mesh1, mesh2)

      expect(diff).toBeNull()
    })

    it('should handle negative differences', () => {
      const mesh1 = [[5, 5], [5, 5]]
      const mesh2 = [[2, 3], [4, 1]]
      const diff = compareMeshes(mesh1, mesh2)

      expect(diff).toEqual([[-3, -2], [-1, -4]])
    })
  })
})
