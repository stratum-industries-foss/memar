import React, { useState, useCallback, useRef, useEffect } from 'react'
import { FloorPlan2D, DevicePosition } from './FloorPlan2D'
import { apiFetch } from './api'

interface FloorPlanEditorProps {
  devices: DevicePosition[]
  imageUrl: string | null
  onLayoutUpdate: (devices: DevicePosition[]) => void
  onUploadImage?: (file: File) => Promise<void>
  onClose?: () => void
  selectedIds?: string[]
  onDeviceClick?: (deviceId: string) => void
  legend?: React.ReactNode
  canEdit?: boolean
  // AI 3D overlay render needs the Higgsfield CLI configured server-side —
  // not available on a stock install. Hide the button entirely rather than
  // show one that's guaranteed to fail; the 2D floor plan works regardless.
  show3DGenerate?: boolean
}

interface Generate3DResponse {
  status: 'pending' | 'ready' | 'failed'
  job_id: number
  image_url?: string
  error?: string
}

export const FloorPlanEditor: React.FC<FloorPlanEditorProps> = ({
  devices,
  imageUrl,
  onLayoutUpdate,
  onUploadImage,
  onClose,
  selectedIds = [],
  onDeviceClick,
  legend,
  canEdit = true,
  show3DGenerate = false,
}) => {
  const [editMode, setEditMode] = useState(false)
  const [localLayout, setLocalLayout] = useState(devices)
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle')

  // 3D Generation state
  const [is3DGenerating, setIs3DGenerating] = useState(false)
  const [image3DUrl, setImage3DUrl] = useState<string | null>(null)
  const [generation3DError, setGeneration3DError] = useState<string | null>(null)
  const [pollJobId, setPollJobId] = useState<number | null>(null)
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Base image upload state
  const [isUploadingImage, setIsUploadingImage] = useState(false)
  const [uploadImageError, setUploadImageError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  React.useEffect(() => {
    if (!editMode) setLocalLayout(devices)
  }, [devices, editMode])

  // The render endpoints require a Bearer token, which a bare URL used as a
  // CSS background-image can't carry — fetch via apiFetch and swap in a blob
  // URL. Revocation is centralized in the effect below (keyed on
  // image3DUrl), which fires on every replacement AND on unmount — a setter
  // here can only catch replacement, not unmount, so it can't be the single
  // owner of the URL's lifecycle.
  const setImage3DFromPath = useCallback(async (path: string) => {
    try {
      const res = await apiFetch(path)
      if (!res.ok) return
      const blob = await res.blob()
      setImage3DUrl(URL.createObjectURL(blob))
    } catch {
      // leave image3DUrl unchanged; generation UI already surfaces errors
    }
  }, [])

  useEffect(() => {
    return () => {
      if (image3DUrl && image3DUrl.startsWith('blob:')) URL.revokeObjectURL(image3DUrl)
    }
  }, [image3DUrl])

  React.useEffect(() => {
    if (!onClose) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleLayoutUpdate = useCallback((updatedDevices: DevicePosition[]) => {
    setLocalLayout(updatedDevices)
  }, [])

  const handleSaveLayout = useCallback(async () => {
    setIsSaving(true)
    setSaveStatus('saving')
    try {
      await onLayoutUpdate(localLayout)
      setSaveStatus('success')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch (err) {
      setSaveStatus('error')
      console.error('Failed to save layout:', err)
    } finally {
      setIsSaving(false)
    }
  }, [localLayout, onLayoutUpdate])

  const handleCancel = useCallback(() => {
    setEditMode(false)
    setLocalLayout(devices)
  }, [devices])

  // "Done Editing" must COMMIT the current layout, not silently drop it. The
  // `if (!editMode) setLocalLayout(devices)` effect above resets localLayout back to
  // `devices` whenever editMode flips false, so merely exiting edit mode discards
  // unsaved edits (identical to Cancel). Persist first; on failure, stay in edit mode.
  const handleDoneEditing = useCallback(async () => {
    setIsSaving(true)
    setSaveStatus('saving')
    try {
      await onLayoutUpdate(localLayout)
      setSaveStatus('success')
      setTimeout(() => setSaveStatus('idle'), 2000)
      setEditMode(false)
    } catch (err) {
      setSaveStatus('error')
      console.error('Failed to save layout:', err)
    } finally {
      setIsSaving(false)
    }
  }, [localLayout, onLayoutUpdate])

  // Poll 3D generation status every 4 seconds
  useEffect(() => {
    if (!pollJobId) return

    const pollStatus = async () => {
      try {
        const response = await apiFetch(`/api/floorplan/image/3d/${pollJobId}`)
        if (!response.ok) {
          setGeneration3DError(`Polling error: HTTP ${response.status}`)
          setIs3DGenerating(false)
          setPollJobId(null)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
          return
        }
        const data: Generate3DResponse = await response.json()

        if (data.status === 'ready' && data.image_url) {
          void setImage3DFromPath(data.image_url)
          setIs3DGenerating(false)
          setPollJobId(null)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
        } else if (data.status === 'failed') {
          setGeneration3DError(data.error || 'Generation failed')
          setIs3DGenerating(false)
          setPollJobId(null)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
        }
      } catch (err) {
        setGeneration3DError(`Polling error: ${String(err)}`)
        setIs3DGenerating(false)
        setPollJobId(null)
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
      }
    }

    pollIntervalRef.current = setInterval(pollStatus, 4000)
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
    }
  }, [pollJobId, setImage3DFromPath])

  const handleGenerate3D = useCallback(async () => {
    setIs3DGenerating(true)
    setGeneration3DError(null)
    try {
      const response = await apiFetch('/api/floorplan/image/3d', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      if (response.status === 429) {
        setGeneration3DError('Daily render quota exceeded (10 renders per 24h)')
        setIs3DGenerating(false)
        return
      }

      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText)
        setGeneration3DError(errText || `Generation failed (HTTP ${response.status})`)
        setIs3DGenerating(false)
        return
      }

      const data: Generate3DResponse = await response.json()

      if (data.status === 'ready' && data.image_url) {
        void setImage3DFromPath(data.image_url)
        setIs3DGenerating(false)
      } else if (data.status === 'pending') {
        setPollJobId(data.job_id)
      } else if (data.status === 'failed') {
        setGeneration3DError(data.error || 'Generation failed')
        setIs3DGenerating(false)
      }
    } catch (err) {
      setGeneration3DError(`Generation error: ${String(err)}`)
      setIs3DGenerating(false)
    }
  }, [setImage3DFromPath])

  const handleFileSelected = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file next time
    if (!file || !onUploadImage) return
    setIsUploadingImage(true)
    setUploadImageError(null)
    try {
      await onUploadImage(file)
      // A 3D render is generated from the prior base image — once that base
      // image changes, the render is stale and would otherwise keep winning
      // the `image3DUrl || imageUrl` precedence in FloorPlan2D, hiding the
      // upload that just succeeded.
      setImage3DUrl(null)
    } catch (err) {
      setUploadImageError(String(err))
    } finally {
      setIsUploadingImage(false)
    }
  }, [onUploadImage])

  // Status counts/key are consolidated into the dashboard status-chip strip.

  return (
    <>
    <div className={`floor-plan-editor${editMode ? ' editing' : ''}`}>
      <div className="floor-plan-editor-header">
        <div className="floor-plan-editor-title">
          <h2>Floor Plan Layout</h2>
        </div>
        <div className="floor-plan-editor-header-actions">
          {onClose && (
            <button className="floor-plan-editor-close" onClick={onClose} aria-label="Dismiss" title="Close floor plan editor">
              ✕
            </button>
          )}
        </div>
      </div>

      {legend && <div className="floor-plan-legend-slot">{legend}</div>}

      <div className={`floor-plan-editor-body${editMode ? ' edit-active' : ''}`}>
        <div className={`floor-plan-editor-content${editMode ? ' edit-active' : ''}`}>
          <FloorPlan2D
            devices={localLayout}
            imageUrl={image3DUrl || imageUrl}
            editMode={editMode}
            onLayoutUpdate={handleLayoutUpdate}
            autoScale={true}
            selectedIds={selectedIds}
            onDeviceClick={onDeviceClick}
          />
          {is3DGenerating && (
            <div className="floor-plan-3d-overlay">
              <div className="floor-plan-3d-spinner">
                <div className="spinner"></div>
                <p>Generating 3D layout...</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {(editMode || saveStatus) && <div className="floor-plan-editor-toolbar">
        {editMode && (
          <>
            <button
              className="floor-plan-btn floor-plan-btn-primary"
              onClick={handleDoneEditing}
              disabled={isSaving}
              title="Save changes and exit edit mode"
            >
              ✓ Done Editing
            </button>
            <button
              className="floor-plan-btn floor-plan-btn-success"
              onClick={handleSaveLayout}
              disabled={isSaving}
              title="Save the current device layout"
            >
              {isSaving ? '⟳ Saving...' : '💾 Save Layout'}
            </button>
            <button
              className="floor-plan-btn floor-plan-btn-danger"
              onClick={handleCancel}
              disabled={isSaving}
              title="Discard unsaved layout changes"
            >
              ✕ Cancel
            </button>
          </>
        )}
        {saveStatus === 'success' && (
          <div className="floor-plan-status-message floor-plan-status-success">
            ✓ Layout saved
          </div>
        )}
        {saveStatus === 'error' && (
          <div className="floor-plan-status-message floor-plan-status-error">
            ✗ Save failed
          </div>
        )}
      </div>}
    </div>

    <div className="floor-plan-editor-meta">
      <span className="floor-plan-device-count">{devices.length} devices</span>
      <div className="floor-plan-editor-actions">
        {!editMode && canEdit && (
          <button
            className="floor-plan-btn floor-plan-btn-primary floor-plan-btn-sm"
            onClick={() => setEditMode(true)}
            title="Enter edit mode to reposition devices"
          >
            ✏️ Edit Layout
          </button>
        )}
        {!editMode && canEdit && show3DGenerate && (
          <button
            className="floor-plan-btn floor-plan-btn-accent floor-plan-btn-sm"
            onClick={handleGenerate3D}
            disabled={is3DGenerating}
            title={image3DUrl ? 'Generate a new 3D layout' : 'Generate 3D layout visualization'}
          >
            {is3DGenerating ? '⟳ Generating...' : '🎨 Generate 3D Layout'}
          </button>
        )}
        {!editMode && canEdit && onUploadImage && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleFileSelected}
              style={{ display: 'none' }}
              aria-hidden="true"
              tabIndex={-1}
            />
            <button
              className="floor-plan-btn floor-plan-btn-sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploadingImage}
              title="Upload a base floor plan image"
            >
              {isUploadingImage ? '⟳ Uploading...' : '📤 Upload Image'}
            </button>
          </>
        )}
        {image3DUrl && (
          <span className="floor-plan-3d-indicator" title="3D layout active">
            ✓ 3D Active
          </span>
        )}
      </div>
      {generation3DError && (
        <div className="floor-plan-3d-error">
          <span>⚠️ {generation3DError}</span>
          <button
            className="floor-plan-btn-inline"
            onClick={() => setGeneration3DError(null)}
          >
            ✕
          </button>
        </div>
      )}
      {uploadImageError && (
        <div className="floor-plan-3d-error">
          <span>⚠️ {uploadImageError}</span>
          <button
            className="floor-plan-btn-inline"
            onClick={() => setUploadImageError(null)}
          >
            ✕
          </button>
        </div>
      )}
    </div>

    </>
  )
}
