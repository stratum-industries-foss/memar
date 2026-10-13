/**
 * KlipperConfigPanel — displays Klipper printer.cfg hardware configuration
 * Shows motion limits, heater temps, sensor types, and hardware features
 */

import React from 'react'
import type { KlipperConfig } from '../types/printer'

interface KlipperConfigPanelProps {
  cfg: KlipperConfig
}

export const KlipperConfigPanel: React.FC<KlipperConfigPanelProps> = ({ cfg }) => {
  return (
    <div className="klipper-config-panel">
      {/* Motion profile */}
      {cfg.kinematics && (
        <section className="config-section">
          <h4>Motion profile</h4>
          <div className="kv-grid">
            <div>
              <span>Kinematics</span>
              <strong>{cfg.kinematics}</strong>
            </div>
            {cfg.max_velocity && (
              <div>
                <span>Max velocity</span>
                <strong>{cfg.max_velocity.toFixed(0)} mm/s</strong>
              </div>
            )}
            {cfg.max_accel && (
              <div>
                <span>Max accel</span>
                <strong>{cfg.max_accel.toFixed(0)} mm/s²</strong>
              </div>
            )}
            {cfg.max_z_velocity && (
              <div>
                <span>Max Z velocity</span>
                <strong>{cfg.max_z_velocity.toFixed(0)} mm/s</strong>
              </div>
            )}
            {cfg.max_z_accel && (
              <div>
                <span>Max Z accel</span>
                <strong>{cfg.max_z_accel.toFixed(0)} mm/s²</strong>
              </div>
            )}
            {cfg.square_corner_velocity && (
              <div>
                <span>Corner velocity</span>
                <strong>{cfg.square_corner_velocity.toFixed(0)} mm/s</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Build envelope */}
      {(cfg.x_max || cfg.y_max || cfg.z_max) && (
        <section className="config-section">
          <h4>Build envelope</h4>
          <div className="kv-grid">
            {cfg.x_max && (
              <div>
                <span>X max</span>
                <strong>{cfg.x_max.toFixed(0)}mm</strong>
              </div>
            )}
            {cfg.y_max && (
              <div>
                <span>Y max</span>
                <strong>{cfg.y_max.toFixed(0)}mm</strong>
              </div>
            )}
            {cfg.z_max && (
              <div>
                <span>Z max</span>
                <strong>{cfg.z_max.toFixed(0)}mm</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Extruder */}
      {(cfg.nozzle_diameter || cfg.filament_diameter || cfg.pressure_advance) && (
        <section className="config-section">
          <h4>Extruder</h4>
          <div className="kv-grid">
            {cfg.nozzle_diameter && (
              <div>
                <span>Nozzle diameter</span>
                <strong>{cfg.nozzle_diameter.toFixed(2)}mm</strong>
              </div>
            )}
            {cfg.filament_diameter && (
              <div>
                <span>Filament diameter</span>
                <strong>{cfg.filament_diameter.toFixed(2)}mm</strong>
              </div>
            )}
            {cfg.pressure_advance && (
              <div>
                <span>Pressure advance</span>
                <strong>{cfg.pressure_advance.toFixed(3)}</strong>
              </div>
            )}
            {cfg.microsteps_e && (
              <div>
                <span>Microsteps (E)</span>
                <strong>{cfg.microsteps_e.toFixed(0)}</strong>
              </div>
            )}
            {cfg.rotation_distance && (
              <div>
                <span>Rotation distance</span>
                <strong>{cfg.rotation_distance.toFixed(2)}</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Heaters */}
      {(cfg.nozzle_max_temp || cfg.bed_max_temp) && (
        <section className="config-section">
          <h4>Heaters</h4>
          <div className="kv-grid">
            {cfg.nozzle_max_temp && (
              <div>
                <span>Nozzle max temp</span>
                <strong>{cfg.nozzle_max_temp.toFixed(0)}°C</strong>
              </div>
            )}
            {cfg.nozzle_sensor_type && (
              <div>
                <span>Nozzle sensor</span>
                <strong>{cfg.nozzle_sensor_type}</strong>
              </div>
            )}
            {cfg.bed_max_temp && (
              <div>
                <span>Bed max temp</span>
                <strong>{cfg.bed_max_temp.toFixed(0)}°C</strong>
              </div>
            )}
            {cfg.bed_sensor_type && (
              <div>
                <span>Bed sensor</span>
                <strong>{cfg.bed_sensor_type}</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Probing */}
      {(cfg.has_probe || cfg.probe_type) && (
        <section className="config-section">
          <h4>Probing</h4>
          <div className="kv-grid">
            <div>
              <span>Probe enabled</span>
              <strong>{cfg.has_probe ? 'Yes' : 'No'}</strong>
            </div>
            {cfg.probe_type && (
              <div>
                <span>Probe type</span>
                <strong>{cfg.probe_type}</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Leveling */}
      {(cfg.has_bed_mesh || cfg.has_z_tilt || cfg.has_quad_gantry_level) && (
        <section className="config-section">
          <h4>Leveling</h4>
          <div className="kv-grid">
            <div>
              <span>Bed mesh</span>
              <strong>{cfg.has_bed_mesh ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Z tilt</span>
              <strong>{cfg.has_z_tilt ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Quad gantry level</span>
              <strong>{cfg.has_quad_gantry_level ? 'Yes' : 'No'}</strong>
            </div>
          </div>
        </section>
      )}

      {/* Fans */}
      {(cfg.fan_count || cfg.heater_fan_count || cfg.controller_fan_count) && (
        <section className="config-section">
          <h4>Cooling</h4>
          <div className="kv-grid">
            {cfg.fan_count && (
              <div>
                <span>Part cooling fans</span>
                <strong>{cfg.fan_count}</strong>
              </div>
            )}
            {cfg.heater_fan_count && (
              <div>
                <span>Heater fans</span>
                <strong>{cfg.heater_fan_count}</strong>
              </div>
            )}
            {cfg.controller_fan_count && (
              <div>
                <span>Controller fans</span>
                <strong>{cfg.controller_fan_count}</strong>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Drivers */}
      {cfg.tmc_drivers && cfg.tmc_drivers.length > 0 && (
        <section className="config-section">
          <h4>Stepper drivers</h4>
          <div className="subtle small">
            {cfg.tmc_drivers.join(', ')}
          </div>
        </section>
      )}

      {/* Sensorless homing */}
      {(cfg.sensorless_x || cfg.sensorless_y) && (
        <section className="config-section">
          <h4>Sensorless homing</h4>
          <div className="kv-grid">
            <div>
              <span>X axis</span>
              <strong>{cfg.sensorless_x ? 'Enabled' : 'No'}</strong>
            </div>
            <div>
              <span>Y axis</span>
              <strong>{cfg.sensorless_y ? 'Enabled' : 'No'}</strong>
            </div>
          </div>
        </section>
      )}

      {/* MCU info */}
      {cfg.mcu_serial && (
        <section className="config-section">
          <h4>Microcontroller</h4>
          <div className="kv-grid">
            <div>
              <span>Serial</span>
              <code className="subtle small">{cfg.mcu_serial}</code>
            </div>
          </div>
        </section>
      )}

      {/* Include files */}
      {cfg.include_files && cfg.include_files.length > 0 && (
        <section className="config-section">
          <h4>Includes</h4>
          <div className="subtle small">
            <ul>
              {cfg.include_files.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {/* Parse notes */}
      {cfg.parse_notes && cfg.parse_notes.length > 0 && (
        <section className="config-section">
          <h4>Parser notes</h4>
          <div className="subtle small">
            {cfg.parse_notes.map((note, idx) => (
              <div key={idx}>• {note}</div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
