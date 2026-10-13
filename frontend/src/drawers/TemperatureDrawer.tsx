import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useTemperatureState } from './useTemperatureState'

const TemperatureDrawer = React.memo(function TemperatureDrawer({
  printerId,
  currentPrinter,
  canWrite,
}: DrawerProps) {
  const {
    customNozzle,
    setCustomNozzle,
    customBed,
    setCustomBed,
    applyPreset,
    applyCustomTemperatures,
    savePresetLabel,
    setSavePresetLabel,
    saveCurrentPreset,
    tempHistoryDetail,
    tempPresets,
    fmtTemp,
  } = useTemperatureState(printerId, currentPrinter)
  return (
    <section className="drawer-section">
      <h3>Temperature controls</h3>
      <div className="kv-grid compact-grid">
        <div><span>Current nozzle</span><strong>{fmtTemp(currentPrinter?.nozzle.temperature ?? null, currentPrinter?.nozzle.target ?? null)}</strong></div>
        <div><span>Current bed</span><strong>{fmtTemp(currentPrinter?.bed.temperature ?? null, currentPrinter?.bed.target ?? null)}</strong></div>
      </div>
      {canWrite && <div className="preset-row drawer-preset-row">
        {tempPresets.map((preset) => <button key={preset.label} onClick={() => void applyPreset(preset.nozzle, preset.bed)}>{preset.label} {preset.nozzle}/{preset.bed}</button>)}
      </div>}
      <div className="temp-grid">
        <label>
          <span>Nozzle target</span>
          <input type="number" value={customNozzle} onChange={(event) => setCustomNozzle(event.target.value)} />
        </label>
        <label>
          <span>Bed target</span>
          <input type="number" value={customBed} onChange={(event) => setCustomBed(event.target.value)} />
        </label>
      </div>
      {canWrite && <div className="inline-actions">
        <button onClick={() => void applyCustomTemperatures()}>Apply temperatures</button>
        {savePresetLabel === null ? (
          <button onClick={() => setSavePresetLabel('')}>Save preset</button>
        ) : (
          <>
            <input
              autoFocus
              value={savePresetLabel}
              onChange={(e) => setSavePresetLabel(e.target.value)}
              placeholder="Preset name"
              style={{ width: 110 }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { saveCurrentPreset(); e.preventDefault() }
                if (e.key === 'Escape') { setSavePresetLabel(null); e.preventDefault() }
              }}
            />
            <button onClick={() => saveCurrentPreset()}>Save</button>
            <button onClick={() => setSavePresetLabel(null)}>Cancel</button>
          </>
        )}
      </div>}
      {tempHistoryDetail && (() => {
        const extData = tempHistoryDetail.extruder
        const bedData = tempHistoryDetail.bed
        if (!extData.length && !bedData.length) return null
        const allTemps = [...extData.map((d) => d.temperature), ...bedData.map((d) => d.temperature)]
        const minT = Math.floor(Math.min(...allTemps) - 5)
        const maxT = Math.ceil(Math.max(...allTemps) + 5)
        const W = 320, H = 100
        const n = Math.max(extData.length, bedData.length)
        const xOf = (i: number, len: number) => Math.round((i / Math.max(len - 1, 1)) * W)
        const yOf = (t: number) => Math.round(H - ((t - minT) / (maxT - minT)) * H)
        const toPath = (pts: Array<{temperature: number}>) =>
          pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(i, pts.length)},${yOf(p.temperature)}`).join(' ')
        return (
          <div style={{marginTop: 12}}>
            <div className="subtle small" style={{marginBottom: 4}}>Temperature history ({extData.length} points)</div>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              width="100%"
              style={{background: 'var(--bg-2,#1a1a1a)', borderRadius: 4, display: 'block'}}
              role="img"
              aria-label="Temperature chart showing nozzle and bed temperature history"
            >
              {extData.length > 1 && <path d={toPath(extData)} fill="none" stroke="var(--temperature-hot)" strokeWidth={1.5} />}
              {bedData.length > 1 && <path d={toPath(bedData)} fill="none" stroke="var(--temperature-cold)" strokeWidth={1.5} />}
            </svg>
            <div className="subtle small" style={{display: 'flex', gap: 10, marginTop: 4}}>
              <span style={{color: 'var(--temperature-hot)'}}>— nozzle</span>
              <span style={{color: 'var(--temperature-cold)'}}>— bed</span>
              <span>{minT}°C – {maxT}°C</span>
            </div>
          </div>
        )
      })()}
    </section>
  )
})

export default TemperatureDrawer
