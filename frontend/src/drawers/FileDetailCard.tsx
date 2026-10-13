/**
 * FileDetailCard — displays detailed information about a selected print file
 * Shows metadata like layer height, filament, estimated time, etc.
 */

import React from 'react'
import type { FileDetailResponse } from '../types/printer'

interface FileDetailCardProps {
  detail: FileDetailResponse
}

export const FileDetailCard: React.FC<FileDetailCardProps> = ({ detail }) => {
  const { file, metadata, compatibility_hints } = detail

  return (
    <div className="file-detail-card">
      <div className="file-name">
        <strong>{file.name}</strong>
        {file.size && <span className="subtle small">{formatBytes(file.size)}</span>}
      </div>

      {Object.keys(metadata).length > 0 && (
        <div className="file-metadata kv-grid">
          {metadata.layer_height && (
            <div>
              <span>Layer height</span>
              <strong>{metadata.layer_height.toFixed(2)}mm</strong>
            </div>
          )}
          {metadata.nozzle_diameter && (
            <div>
              <span>Nozzle</span>
              <strong>{metadata.nozzle_diameter.toFixed(2)}mm</strong>
            </div>
          )}
          {metadata.filament_total && (
            <div>
              <span>Filament</span>
              <strong>{metadata.filament_total.toFixed(0)}mm</strong>
            </div>
          )}
          {metadata.filament_weight_total && (
            <div>
              <span>Weight</span>
              <strong>{metadata.filament_weight_total.toFixed(1)}g</strong>
            </div>
          )}
          {metadata.estimated_time_formatted && (
            <div>
              <span>Est. time</span>
              <strong>{metadata.estimated_time_formatted}</strong>
            </div>
          )}
          {metadata.extruder_temperature && (
            <div>
              <span>Nozzle temp</span>
              <strong>{metadata.extruder_temperature.toFixed(0)}°C</strong>
            </div>
          )}
          {metadata.bed_temperature && (
            <div>
              <span>Bed temp</span>
              <strong>{metadata.bed_temperature.toFixed(0)}°C</strong>
            </div>
          )}
          {metadata.chamber_temperature && (
            <div>
              <span>Chamber temp</span>
              <strong>{metadata.chamber_temperature.toFixed(0)}°C</strong>
            </div>
          )}
        </div>
      )}

      {compatibility_hints && compatibility_hints.length > 0 && (
        <div className="file-hints subtle small">
          <strong>Notes:</strong>
          <ul>
            {compatibility_hints.map((hint, idx) => (
              <li key={idx}>{hint}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/**
 * Format bytes to human-readable size
 */
function formatBytes(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIdx = 0
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024
    unitIdx++
  }
  return `${size.toFixed(1)} ${units[unitIdx]}`
}
