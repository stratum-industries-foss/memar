import React, { useCallback } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useTimelapseState } from './useTimelapseState'
import { formatBytes, formatTimestamp } from './formatUtils'
import { apiFetch } from '../api'

/**
 * TimelapseMedia — Sub-component for loading and downloading timelapse files
 *
 * Handles blob URL creation with Bearer auth and playback/download controls.
 * Defined locally (not exported from App) to avoid circular dependency with
 * lazy-loaded drawers.
 */
const TimelapseMedia = React.memo(function TimelapseMedia({
  printerId,
  name,
  showVideo,
}: {
  printerId: string
  name: string
  showVideo: boolean
}) {
  const [blobUrl, setBlobUrl] = React.useState<string | null>(null)
  const [downloading, setDownloading] = React.useState(false)
  const [loading, setLoading] = React.useState(false)

  // /timelapse/{name} requires a Bearer header, which neither <video src> nor
  // <a href download> can carry — fetch once via apiFetch and reuse the blob URL
  // for both playback and download. Fetched ON DEMAND (button click), NOT on
  // mount, so opening the timelapse tab doesn't download every video in full.
  const ensureBlob = React.useCallback(async (): Promise<string | null> => {
    if (blobUrl) return blobUrl
    setLoading(true)
    try {
      const res = await apiFetch(`/api/printers/${printerId}/timelapse/${encodeURIComponent(name)}`)
      if (!res.ok) return null
      // Note: jsdom doesn't support URL.createObjectURL in tests; see setupTests.ts
      const url = URL.createObjectURL(await res.blob())
      setBlobUrl(url)
      return url
    } catch {
      return null
    } finally {
      setLoading(false)
    }
  }, [printerId, name, blobUrl])

  React.useEffect(() => {
    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [blobUrl])

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const url = await ensureBlob()
      if (!url) return
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
    } finally {
      setDownloading(false)
    }
  }

  return (
    <>
      {showVideo &&
        (blobUrl ? (
          <video
            src={blobUrl}
            controls
            style={{ width: '100%', maxHeight: 200, marginTop: 6 }}
            aria-label={`Timelapse video: ${name}`}
          />
        ) : (
          <button onClick={() => void ensureBlob()} disabled={loading} className="action-btn">
            {loading ? 'Loading…' : '▶ Load video'}
          </button>
        ))}
      <button onClick={() => void handleDownload()} disabled={downloading} className="action-btn">
        ⬇ Download
      </button>
    </>
  )
})

/**
 * TimelapseDrawer — Timelapse file browser and playback
 *
 * Displays configured timelapse directory and recent timelapse artifacts (videos/images).
 * Allows loading, playback, and download of timelapse files.
 * Does not require canWrite (read-only access sufficient).
 */
const TimelapseDrawer = React.memo(function TimelapseDrawer({ printerId, ...props }: DrawerProps) {
  if (!printerId) return null

  const { data, error, loading, playbackSpeed, reload, setPlaybackSpeed } = useTimelapseState(printerId)

  return (
    <section className="drawer-section">
      <h3>Timelapse</h3>

      {/* Refresh button */}
      <div className="file-toolbar" style={{ marginBottom: 8 }}>
        <button
          onClick={() => {
            void reload()
          }}
          disabled={loading}
          aria-label="Refresh timelapse list"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Error state */}
      {error && <div style={{ color: 'var(--color-danger)', marginBottom: 8 }} aria-live="polite">{error}</div>}

      {/* Loading state */}
      {loading && data === null && <div className="subtle">Loading…</div>}

      {/* Not configured state */}
      {data !== null && !data.configured && (
        <div className="subtle">No timelapse directory is configured for this printer yet.</div>
      )}

      {/* Configured state: source directory + file list */}
      {data?.configured && (
        <>
          <div className="subtle">Source directory: {data.source_dir || '—'}</div>

          {/* Playback speed control (for client-side video playback) */}
          {data.entries.length > 0 && (
            <div style={{ marginTop: 8, marginBottom: 8 }}>
              <label
                htmlFor="playback-speed"
                style={{ display: 'block', fontSize: '0.85rem', marginBottom: 4, color: 'var(--text-secondary)' }}
              >
                Playback speed
              </label>
              <select
                id="playback-speed"
                value={playbackSpeed}
                onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
                style={{ width: '100%' }}
              >
                <option value={0.5}>0.5x</option>
                <option value={1}>1x (normal)</option>
                <option value={1.5}>1.5x</option>
                <option value={2}>2x</option>
              </select>
            </div>
          )}

          {/* File list */}
          <div className="file-list timelapse-list">
            {data.entries.length === 0 && <div className="subtle">No recent timelapse artifacts found.</div>}
            {data.entries.map((entry) => (
              <div key={entry.id} className="file-row file-row-flex">
                <div style={{ flex: 1 }}>
                  <strong>{entry.name}</strong>
                  <div className="subtle small">
                    {entry.kind} • {formatBytes(entry.size)} • {formatTimestamp(entry.modified)}
                  </div>
                </div>
                <TimelapseMedia printerId={printerId} name={entry.name} showVideo={entry.kind === 'video'} />
              </div>
            ))}
          </div>

          {/* Feature availability notes */}
          <div style={{ marginTop: 16, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            <div className="subtle small" style={{ marginBottom: 8 }}>
              💡 Frame rate, resolution, and enable/disable timelapse are not exposed by the backend API.
            </div>
            <div className="subtle small">
              Playback speed is applied client-side to loaded videos only.
            </div>
          </div>
        </>
      )}
    </section>
  )
})

export default TimelapseDrawer

