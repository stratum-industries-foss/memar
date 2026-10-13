/**
 * 3D Bed Mesh Visualizer using three.js
 * Renders bed mesh data as an interactive 3D surface with color gradient
 */

import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
// @ts-ignore - OrbitControls doesn't have full TypeScript definitions
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls'
import { normalizedZToColor, rgbToCss, upsampleMeshBicubic } from './meshUtils'

type RenderMode = 'solid' | 'wireframe' | 'transparent'

interface BedMeshVisualizerProps {
  matrix: number[][]
  minZ: number | null
  maxZ: number | null
  extent?: {
    x_min: number | null
    x_max: number | null
    y_min: number | null
    y_max: number | null
  }
  renderMode?: RenderMode
  title?: string
}

const BedMeshVisualizer = React.memo(function BedMeshVisualizer({
  matrix,
  minZ,
  maxZ,
  extent,
  renderMode = 'solid',
  title,
}: BedMeshVisualizerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const meshRef = useRef<THREE.Mesh | null>(null)
  const controlsRef = useRef<InstanceType<typeof OrbitControls> | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const animationIdRef = useRef<number | null>(null)

  useEffect(() => {
    if (!containerRef.current || failed || !matrix || matrix.length === 0) {
      setLoading(false)
      return
    }

    let mounted = true

    try {
      // Scene setup
      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0x1a1a1a)
      scene.fog = new THREE.Fog(0x1a1a1a, 50, 100)

      const width = containerRef.current.clientWidth
      const height = containerRef.current.clientHeight
      if (width === 0 || height === 0) {
        setLoading(false)
        return
      }

      const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000)

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
      renderer.setSize(width, height)
      renderer.setPixelRatio(window.devicePixelRatio)
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFShadowMap

      // Handle WebGL context loss
      renderer.domElement.addEventListener(
        'webglcontextlost',
        (e) => {
          e.preventDefault()
          if (mounted) {
            setFailed(true)
          }
        },
        false
      )

      containerRef.current.appendChild(renderer.domElement)

      // Lighting
      const directionalLight = new THREE.DirectionalLight(0xffffff, 1.2)
      directionalLight.position.set(10, 15, 10)
      directionalLight.castShadow = true
      directionalLight.shadow.mapSize.width = 1024
      directionalLight.shadow.mapSize.height = 1024
      directionalLight.shadow.camera.far = 50
      scene.add(directionalLight)

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.6)
      scene.add(ambientLight)

      // Build geometry from mesh data
      const upsampledMatrix = upsampleMeshBicubic(matrix, 2)
      const rows = upsampledMatrix.length
      const cols = upsampledMatrix[0]?.length || 0

      // Calculate extents
      const xMin = extent?.x_min ?? 0
      const xMax = extent?.x_max ?? cols - 1
      const yMin = extent?.y_min ?? 0
      const yMax = extent?.y_max ?? rows - 1
      const zMin = minZ ?? 0
      const zMax = maxZ ?? 1

      // Create mesh geometry
      const geometry = new THREE.BufferGeometry()
      const vertices: number[] = []
      const colors: number[] = []

      // Build vertices and colors
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          const z = upsampledMatrix[y][x]

          // Position in world space
          const worldX = xMin + ((x / (cols - 1)) * (xMax - xMin) || 0)
          const worldY = yMin + ((y / (rows - 1)) * (yMax - yMin) || 0)
          const worldZ = zMin === zMax ? z : (z - zMin) / (zMax - zMin) * 5

          vertices.push(worldX, worldY, worldZ)

          // Color based on Z height
          const normalized = zMin === zMax ? 0.5 : (z - zMin) / (zMax - zMin)
          const [r, g, b] = normalizedZToColor(normalized)
          colors.push(r / 255, g / 255, b / 255)
        }
      }

      // Build indices for faces
      const indices: number[] = []
      for (let y = 0; y < rows - 1; y++) {
        for (let x = 0; x < cols - 1; x++) {
          const a = y * cols + x
          const b = y * cols + x + 1
          const c = (y + 1) * cols + x
          const d = (y + 1) * cols + x + 1

          // Two triangles per quad
          indices.push(a, c, b)
          indices.push(b, c, d)
        }
      }

      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertices), 3))
      geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(colors), 3))
      geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(indices), 1))
      geometry.computeVertexNormals()

      // Material
      const material = new THREE.MeshPhongMaterial({
        vertexColors: true,
        emissive: 0x000000,
        shininess: 30,
        side: THREE.DoubleSide,
        wireframe: renderMode === 'wireframe',
        transparent: renderMode === 'transparent',
        opacity: renderMode === 'transparent' ? 0.8 : 1,
      })

      const meshObj = new THREE.Mesh(geometry, material)
      meshObj.castShadow = true
      meshObj.receiveShadow = true
      scene.add(meshObj)
      meshRef.current = meshObj

      // Center and auto-fit camera
      const box = new THREE.Box3().setFromObject(meshObj)
      const center = box.getCenter(new THREE.Vector3())
      const size = box.getSize(new THREE.Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      const fov = camera.fov * (Math.PI / 180)
      let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2))

      camera.position.set(center.x, center.y + size.y * 0.3, center.z + cameraZ * 0.8)
      camera.lookAt(center)
      camera.far = Math.max(100, cameraZ * 3)
      camera.updateProjectionMatrix()

      // Orbit controls
      const controls = new OrbitControls(camera, renderer.domElement)
      controls.target.copy(center)
      controls.enableDamping = true
      controls.dampingFactor = 0.05
      controls.autoRotate = false
      controls.autoRotateSpeed = 0
      controls.enablePan = true
      controls.enableZoom = true
      controls.update()
      controlsRef.current = controls

      sceneRef.current = scene
      rendererRef.current = renderer

      setLoading(false)

      // Animation loop
      const animate = () => {
        if (!mounted) return
        animationIdRef.current = requestAnimationFrame(animate)

        controls.update()
        renderer.render(scene, camera)
      }
      animate()

      // Handle resize
      const handleResize = () => {
        if (!containerRef.current || !renderer) return
        const newWidth = containerRef.current.clientWidth
        const newHeight = containerRef.current.clientHeight
        if (newWidth > 0 && newHeight > 0) {
          camera.aspect = newWidth / newHeight
          camera.updateProjectionMatrix()
          renderer.setSize(newWidth, newHeight)
        }
      }

      window.addEventListener('resize', handleResize)

      const resizeObserver = new ResizeObserver(() => {
        if (!mounted) return
        handleResize()
      })
      if (containerRef.current) {
        resizeObserver.observe(containerRef.current)
      }

      return () => {
        mounted = false
        window.removeEventListener('resize', handleResize)
        resizeObserver.disconnect()

        if (animationIdRef.current !== null) {
          cancelAnimationFrame(animationIdRef.current)
          animationIdRef.current = null
        }

        // Cleanup scene resources
        if (sceneRef.current) {
          sceneRef.current.traverse((child) => {
            if ('geometry' in child) {
              (child as any).geometry?.dispose()
            }
            if ('material' in child) {
              const mat = (child as any).material
              if (Array.isArray(mat)) {
                mat.forEach((m) => m.dispose?.())
              } else {
                mat?.dispose?.()
              }
            }
          })
        }

        // Cleanup renderer
        if (containerRef.current && rendererRef.current && rendererRef.current.domElement) {
          try {
            containerRef.current.removeChild(rendererRef.current.domElement)
          } catch (e) {
            // Already removed
          }
        }

        if (controlsRef.current) {
          controlsRef.current.dispose()
          controlsRef.current = null
        }

        rendererRef.current?.dispose()
        rendererRef.current = null
      }
    } catch (e) {
      setLoading(false)
      setFailed(true)
      return undefined
    }
  }, [matrix, minZ, maxZ, extent, renderMode])

  if (failed) {
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
          fontSize: '0.9rem',
        }}
      >
        Unable to render 3D mesh. Please try the 2D heatmap view.
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={title || '3D Bed Mesh Visualization - Interactive 3D view showing bed surface topology. Use mouse to rotate, scroll to zoom, and right-click to pan.'}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        background: loading ? 'var(--surface-l2)' : 'var(--surface-base)',
      }}
    >
      {loading && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            fontSize: '14px',
            color: 'var(--text-secondary)',
            pointerEvents: 'none',
          }}
        >
          Rendering 3D mesh...
        </div>
      )}
    </div>
  )
})

export default BedMeshVisualizer
