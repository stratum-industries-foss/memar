/**
 * MaterialSelector — preset material library and custom material management
 *
 * Allows users to:
 * - Browse preset materials (PLA, PETG, ABS, TPU, Nylon)
 * - View material properties (nozzle/bed temps, speeds, retraction)
 * - Select and apply a material
 * - Save custom materials
 */

import React, { useState, useCallback } from 'react'
import type { Material } from '../types/material'
import { DEFAULT_MATERIALS } from '../types/material'
import styles from './MaterialSelector.module.css'

interface MaterialSelectorProps {
  onApply?: (materialName: string) => void
  currentMaterial?: string | null
  disabled?: boolean
}

export const MaterialSelector: React.FC<MaterialSelectorProps> = ({
  onApply,
  currentMaterial,
  disabled = false,
}) => {
  const [expanded, setExpanded] = useState(false)
  const [customMaterials, setCustomMaterials] = useState<Material[]>([])
  const [showCustomForm, setShowCustomForm] = useState(false)
  const [formData, setFormData] = useState<Partial<Material>>({
    name: '',
    nozzle_temp_c: 200,
    bed_temp_c: 60,
    print_speed_mm_s: 50,
    retraction_distance_mm: 5,
    retraction_speed_mm_s: 45,
  })

  const allMaterials = [...DEFAULT_MATERIALS, ...customMaterials]

  const handleApply = useCallback((material: Material) => {
    if (onApply) {
      onApply(material.name)
    }
    setExpanded(false)
  }, [onApply])

  const handleSaveCustom = useCallback(() => {
    if (!formData.name) {
      alert('Material name is required')
      return
    }
    const newMaterial: Material = {
      id: `custom-${Date.now()}`,
      name: formData.name,
      nozzle_temp_c: formData.nozzle_temp_c ?? 200,
      bed_temp_c: formData.bed_temp_c ?? 60,
      print_speed_mm_s: formData.print_speed_mm_s ?? 50,
      retraction_distance_mm: formData.retraction_distance_mm ?? 5,
      retraction_speed_mm_s: formData.retraction_speed_mm_s ?? 45,
      description: formData.description,
      color: formData.color,
    }
    setCustomMaterials([...customMaterials, newMaterial])
    setFormData({
      name: '',
      nozzle_temp_c: 200,
      bed_temp_c: 60,
      print_speed_mm_s: 50,
      retraction_distance_mm: 5,
      retraction_speed_mm_s: 45,
    })
    setShowCustomForm(false)
  }, [formData, customMaterials])

  return (
    <div className={styles['material-selector']}>
      <button
        onClick={() => setExpanded(!expanded)}
        disabled={disabled}
        className="action-btn"
        style={{ width: '100%', textAlign: 'left' }}
      >
        {expanded ? '▴ Material library' : '▾ Material library'}
      </button>

      {expanded && (
        <div className={styles['material-library']} role="group" aria-label="Material Presets Library">
          <div className={styles['material-grid']}>
            {allMaterials.map((mat) => (
              <div
                key={mat.id || mat.name}
                className={styles['material-card']}
                role="button"
                tabIndex={0}
                onClick={() => handleApply(mat)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleApply(mat)
                  }
                }}
                aria-label={`Material: ${mat.name}. Nozzle: ${mat.nozzle_temp_c}°C, Bed: ${mat.bed_temp_c}°C, Speed: ${mat.print_speed_mm_s}mm/s${mat.description ? `. ${mat.description}` : ''}`}
                style={{
                  borderColor: currentMaterial === mat.name ? 'var(--accent-solid)' : undefined,
                  backgroundColor:
                    currentMaterial === mat.name ? 'var(--surface-l2)' : 'var(--surface-l1)',
                  cursor: 'pointer',
                }}
              >
                {mat.color && (
                  <div
                    className={styles['material-color-swatch']}
                    style={{ backgroundColor: mat.color }}
                  />
                )}
                <div className={styles['material-card-content']}>
                  <div className={styles['material-name']}>{mat.name}</div>
                  {mat.description && (
                    <div className={styles['material-description']}>{mat.description}</div>
                  )}
                  <div className={styles['material-specs']}>
                    <div>
                      <span className={styles['spec-label']}>Nozzle</span>
                      <span>{mat.nozzle_temp_c}°C</span>
                    </div>
                    <div>
                      <span className={styles['spec-label']}>Bed</span>
                      <span>{mat.bed_temp_c}°C</span>
                    </div>
                    <div>
                      <span className={styles['spec-label']}>Speed</span>
                      <span>{mat.print_speed_mm_s}mm/s</span>
                    </div>
                    <div>
                      <span className={styles['spec-label']}>Retract</span>
                      <span>{mat.retraction_distance_mm}mm</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {!showCustomForm && (
            <button
              onClick={() => setShowCustomForm(true)}
              className="action-btn"
              style={{ fontSize: '0.8rem', marginTop: 12, width: '100%' }}
            >
              + Add custom material
            </button>
          )}

          {showCustomForm && (
            <div className={styles['custom-form']}>
              <h4 style={{ marginTop: 12, marginBottom: 8 }}>Create custom material</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <label htmlFor="mat-name" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Material name <span style={{ color: 'var(--color-danger)' }}>*</span></label>
                  <input
                    id="mat-name"
                    type="text"
                    placeholder="Material name"
                    value={formData.name || ''}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    aria-required="true"
                    style={{ padding: '6px', fontSize: '0.85rem', width: '100%' }}
                  />
                </div>
                <div>
                  <label htmlFor="mat-desc" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Description (optional)</label>
                  <input
                    id="mat-desc"
                    type="text"
                    placeholder="Description (optional)"
                    value={formData.description || ''}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    style={{ padding: '6px', fontSize: '0.85rem', width: '100%' }}
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <div>
                    <label htmlFor="mat-nozzle" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Nozzle (°C)</label>
                    <input
                      id="mat-nozzle"
                      type="number"
                      value={formData.nozzle_temp_c || 200}
                      onChange={(e) =>
                        setFormData({ ...formData, nozzle_temp_c: parseInt(e.target.value) })
                      }
                      style={{ width: '100%', padding: '4px', fontSize: '0.85rem' }}
                    />
                  </div>
                  <div>
                    <label htmlFor="mat-bed" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Bed (°C)</label>
                    <input
                      id="mat-bed"
                      type="number"
                      value={formData.bed_temp_c || 60}
                      onChange={(e) =>
                        setFormData({ ...formData, bed_temp_c: parseInt(e.target.value) })
                      }
                      style={{ width: '100%', padding: '4px', fontSize: '0.85rem' }}
                    />
                  </div>
                  <div>
                    <label htmlFor="mat-speed" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Speed (mm/s)</label>
                    <input
                      id="mat-speed"
                      type="number"
                      value={formData.print_speed_mm_s || 50}
                      onChange={(e) =>
                        setFormData({ ...formData, print_speed_mm_s: parseInt(e.target.value) })
                      }
                      style={{ width: '100%', padding: '4px', fontSize: '0.85rem' }}
                    />
                  </div>
                  <div>
                    <label htmlFor="mat-retract-dist" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Retraction (mm)</label>
                    <input
                      id="mat-retract-dist"
                      type="number"
                      value={formData.retraction_distance_mm || 5}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retraction_distance_mm: parseInt(e.target.value),
                        })
                      }
                      style={{ width: '100%', padding: '4px', fontSize: '0.85rem' }}
                    />
                  </div>
                  <div>
                    <label htmlFor="mat-color" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Color</label>
                    <input
                      id="mat-color"
                      type="color"
                      value={formData.color || '#E0E0E0'}
                      onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                      style={{ width: '100%', height: 32, padding: '2px', fontSize: '0.85rem' }}
                    />
                  </div>
                  <div>
                    <label htmlFor="mat-retract-speed" style={{ fontSize: '0.75rem', opacity: 0.7, display: 'block', marginBottom: 4 }}>Retract speed (mm/s)</label>
                    <input
                      id="mat-retract-speed"
                      type="number"
                      value={formData.retraction_speed_mm_s || 45}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          retraction_speed_mm_s: parseInt(e.target.value),
                        })
                      }
                      style={{ width: '100%', padding: '4px', fontSize: '0.85rem' }}
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
                  <button
                    onClick={() => setShowCustomForm(false)}
                    className="action-btn"
                    style={{ fontSize: '0.8rem', padding: '4px 12px' }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveCustom}
                    className="action-btn"
                    style={{
                      fontSize: '0.8rem',
                      padding: '4px 12px',
                      backgroundColor: 'var(--color-success)',
                      color: '#fff',
                    }}
                  >
                    Save material
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default MaterialSelector
