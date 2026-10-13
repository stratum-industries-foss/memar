import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
// @ts-ignore - Three.js examples module doesn't have type definitions
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader'

interface GLTF {
  scene: THREE.Group
  scenes: THREE.Group[]
  animations: THREE.AnimationClip[]
  asset: any
  parser: any
  userData: any
}

interface ThreeDViewerProps {
  src: string
  alt: string
  fallback: React.ReactNode
}

const ThreeDViewer = React.memo(function ThreeDViewer({ src, alt, fallback }: ThreeDViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const modelRef = useRef<THREE.Group | null>(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const animationIdRef = useRef<number | null>(null)

  useEffect(() => {
    if (!containerRef.current || failed) {
      setLoading(false)
      return
    }

    let mounted = true

    try {
      // Scene setup
      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0xf5f5f5)

      const width = containerRef.current.clientWidth
      const height = containerRef.current.clientHeight
      const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000)
      camera.position.z = 5

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setSize(width, height)
      renderer.setPixelRatio(window.devicePixelRatio)

      // Handle WebGL context loss (browsers limit ~16 contexts)
      renderer.domElement.addEventListener('webglcontextlost', (e) => {
        e.preventDefault()
        if (mounted) {
          setFailed(true)
        }
      }, false)

      containerRef.current.appendChild(renderer.domElement)

      // Lighting
      const directionalLight = new THREE.DirectionalLight(0xffffff, 1.0)
      directionalLight.position.set(5, 5, 5)
      scene.add(directionalLight)

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
      scene.add(ambientLight)

      // Load GLB
      const loader = new GLTFLoader()
      loader.load(
        src,
        (gltf: GLTF) => {
          if (!mounted) return

          const model = gltf.scene
          model.scale.set(2.5, 2.5, 2.5)

          // Center the model
          const box = new THREE.Box3().setFromObject(model)
          const center = box.getCenter(new THREE.Vector3())
          model.position.sub(center)

          scene.add(model)
          modelRef.current = model

          setLoading(false)

          // Auto-rotate animation
          const animate = () => {
            if (!mounted) return
            animationIdRef.current = requestAnimationFrame(animate)

            if (model) {
              model.rotation.y += 0.003
            }
            renderer.render(scene, camera)
          }
          animate()
        },
        undefined,
        () => {
          if (!mounted) return
          setLoading(false)
          setFailed(true)
        }
      )

      sceneRef.current = scene
      rendererRef.current = renderer

      // Handle window resize
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

      // Handle container resize (CSS changes, HMR)
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

        // Cancel any pending animation frame
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

        // Remove and dispose renderer
        if (containerRef.current && rendererRef.current && rendererRef.current.domElement) {
          try {
            containerRef.current.removeChild(rendererRef.current.domElement)
          } catch (e) {
            // Already removed
          }
        }

        renderer.dispose()
        rendererRef.current = null
      }
    } catch (e) {
      setLoading(false)
      setFailed(true)
      return undefined
    }
  }, [src, failed])

  if (failed || !src) {
    return <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{fallback}</div>
  }

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        background: loading ? '#f5f5f5' : 'transparent',
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
            color: '#999',
          }}
        >
          Loading 3D model...
        </div>
      )}
    </div>
  )
})

export default ThreeDViewer
