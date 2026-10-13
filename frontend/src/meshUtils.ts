/**
 * Bed mesh utilities: interpolation, color mapping, statistics
 * Pure functions for mesh data processing
 */

/**
 * Color gradient: blue (low) → green (mid) → red (high)
 * Maps normalized [0,1] to RGB color string
 */
export function normalizedZToColor(normalized: number): [number, number, number] {
  // Clamp to [0, 1]
  const n = Math.max(0, Math.min(1, normalized));

  if (n < 0.5) {
    // Blue (0) → Cyan (0.5)
    const t = n * 2; // 0 to 1
    return [
      Math.round(t * 255),      // R: 0 → 255
      Math.round(80 + t * 100), // G: 80 → 180
      255                        // B: 255
    ];
  } else {
    // Cyan (0.5) → Red (1.0)
    const t = (n - 0.5) * 2; // 0 to 1
    return [
      255,                         // R: 255
      Math.round(180 - t * 100),   // G: 180 → 80
      Math.round(255 - t * 255)    // B: 255 → 0
    ];
  }
}

/**
 * Convert RGB to CSS color string
 */
export function rgbToCss(r: number, g: number, b: number): string {
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Get color string for a Z value given global min/max
 */
export function zToColorString(z: number | null, minZ: number | null, maxZ: number | null): string {
  if (z === null || minZ === null || maxZ === null) {
    return rgbToCss(128, 128, 128); // Gray for unknown
  }

  if (minZ === maxZ) {
    return rgbToCss(128, 128, 128); // Gray for flat surface
  }

  const normalized = (z - minZ) / (maxZ - minZ);
  const [r, g, b] = normalizedZToColor(normalized);
  return rgbToCss(r, g, b);
}

/**
 * Calculate min/max/average Z height for a matrix
 */
export interface MeshStats {
  minZ: number;
  maxZ: number;
  avgZ: number;
  flatness: number; // max - min
  pointCount: number;
  gridWidth: number;
  gridHeight: number;
}

export function calculateMeshStats(matrix: number[][]): MeshStats {
  const flatMatrix = matrix.flat();
  const minZ = Math.min(...flatMatrix);
  const maxZ = Math.max(...flatMatrix);
  const avgZ = flatMatrix.reduce((a, b) => a + b, 0) / flatMatrix.length;

  return {
    minZ,
    maxZ,
    avgZ,
    flatness: maxZ - minZ,
    pointCount: flatMatrix.length,
    gridWidth: matrix[0]?.length || 0,
    gridHeight: matrix.length,
  };
}

/**
 * Bicubic interpolation upsampling of a regular grid
 * Smoothly interpolates values between known grid points
 *
 * @param matrix Input grid as 2D array
 * @param scale Upsample factor (e.g., 2 = double resolution)
 * @returns Upsampled matrix with smooth interpolation
 */
export function upsampleMeshBicubic(matrix: number[][], scale: number = 2): number[][] {
  if (matrix.length === 0 || matrix[0].length === 0 || scale <= 1) return matrix;

  const height = matrix.length;
  const width = matrix[0].length;

  // Simple linear interpolation for small meshes to avoid artifacts
  if (height < 2 || width < 2) {
    return matrix;
  }

  const newHeight = (height - 1) * scale + 1;
  const newWidth = (width - 1) * scale + 1;
  const upsampled: number[][] = [];

  // Helper: Catmull-Rom basis function for bicubic interpolation
  const catmullRom = (p0: number, p1: number, p2: number, p3: number, t: number): number => {
    const t2 = t * t;
    const t3 = t2 * t;

    return 0.5 * (
      2 * p1 +
      (-p0 + p2) * t +
      (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
      (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    );
  };

  // Interpolate
  for (let newY = 0; newY < newHeight; newY++) {
    upsampled[newY] = [];

    // Map from new space to original space
    const origY = (newY / (newHeight - 1)) * (height - 1);

    for (let newX = 0; newX < newWidth; newX++) {
      // Map from new space to original space
      const origX = (newX / (newWidth - 1)) * (width - 1);

      const ix = Math.floor(origX);
      const iy = Math.floor(origY);
      const fx = origX - ix;
      const fy = origY - iy;

      // Clamp indices to valid range
      const iy0 = Math.max(0, Math.min(height - 1, iy - 1));
      const iy1 = Math.max(0, Math.min(height - 1, iy));
      const iy2 = Math.max(0, Math.min(height - 1, iy + 1));
      const iy3 = Math.max(0, Math.min(height - 1, iy + 2));

      const ix0 = Math.max(0, Math.min(width - 1, ix - 1));
      const ix1 = Math.max(0, Math.min(width - 1, ix));
      const ix2 = Math.max(0, Math.min(width - 1, ix + 1));
      const ix3 = Math.max(0, Math.min(width - 1, ix + 2));

      // Get 4x4 neighborhood
      const rows = [
        [matrix[iy0][ix0], matrix[iy0][ix1], matrix[iy0][ix2], matrix[iy0][ix3]],
        [matrix[iy1][ix0], matrix[iy1][ix1], matrix[iy1][ix2], matrix[iy1][ix3]],
        [matrix[iy2][ix0], matrix[iy2][ix1], matrix[iy2][ix2], matrix[iy2][ix3]],
        [matrix[iy3][ix0], matrix[iy3][ix1], matrix[iy3][ix2], matrix[iy3][ix3]],
      ];

      // Interpolate rows (x-direction)
      const interpolatedRows = rows.map((row) =>
        catmullRom(row[0], row[1], row[2], row[3], fx)
      );

      // Interpolate columns (y-direction)
      const value = catmullRom(interpolatedRows[0], interpolatedRows[1], interpolatedRows[2], interpolatedRows[3], fy);
      upsampled[newY][newX] = value;
    }
  }

  return upsampled;
}

/**
 * Create a simple flat mesh for comparison
 */
export function createFlatMesh(width: number, height: number, zValue: number = 0): number[][] {
  return Array.from({ length: height }, () => Array(width).fill(zValue));
}

/**
 * Create a tilted mesh for testing
 */
export function createTiltedMesh(width: number, height: number, tiltX: number, tiltY: number): number[][] {
  const mesh: number[][] = [];
  for (let y = 0; y < height; y++) {
    mesh[y] = [];
    for (let x = 0; x < width; x++) {
      const normalizedX = x / (width - 1);
      const normalizedY = y / (height - 1);
      mesh[y][x] = normalizedX * tiltX + normalizedY * tiltY;
    }
  }
  return mesh;
}

/**
 * Create a curved mesh for testing (paraboloid)
 */
export function createCurvedMesh(width: number, height: number, curvature: number): number[][] {
  const mesh: number[][] = [];
  const centerX = (width - 1) / 2;
  const centerY = (height - 1) / 2;
  const maxDist = Math.max(centerX, centerY);

  for (let y = 0; y < height; y++) {
    mesh[y] = [];
    for (let x = 0; x < width; x++) {
      const dx = (x - centerX) / maxDist;
      const dy = (y - centerY) / maxDist;
      const dist = Math.sqrt(dx * dx + dy * dy);
      mesh[y][x] = (dist * dist - 1) * curvature;
    }
  }
  return mesh;
}

/**
 * Create a wavy mesh for testing
 */
export function createWavyMesh(width: number, height: number, amplitude: number, frequency: number): number[][] {
  const mesh: number[][] = [];
  for (let y = 0; y < height; y++) {
    mesh[y] = [];
    for (let x = 0; x < width; x++) {
      const normalizedX = (x / (width - 1)) * Math.PI * 2;
      const normalizedY = (y / (height - 1)) * Math.PI * 2;
      mesh[y][x] = Math.sin(normalizedX * frequency) * Math.cos(normalizedY * frequency) * amplitude;
    }
  }
  return mesh;
}

/**
 * Validate mesh data structure
 */
export function isValidMesh(matrix: any): matrix is number[][] {
  if (!Array.isArray(matrix) || matrix.length === 0) return false;
  if (!Array.isArray(matrix[0]) || matrix[0].length === 0) return false;

  // Check all rows have same length and contain numbers
  const width = matrix[0].length;
  return matrix.every((row) =>
    Array.isArray(row) &&
    row.length === width &&
    row.every((val) => typeof val === 'number' && isFinite(val))
  );
}

/**
 * Compare two meshes and return difference matrix
 */
export function compareMeshes(mesh1: number[][], mesh2: number[][]): number[][] | null {
  if (mesh1.length !== mesh2.length || mesh1[0].length !== mesh2[0].length) {
    return null; // Incompatible sizes
  }

  const diff: number[][] = [];
  for (let y = 0; y < mesh1.length; y++) {
    diff[y] = [];
    for (let x = 0; x < mesh1[0].length; x++) {
      diff[y][x] = mesh2[y][x] - mesh1[y][x];
    }
  }
  return diff;
}
