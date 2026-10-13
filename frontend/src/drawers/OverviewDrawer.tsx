import React, { useState, useEffect } from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { MachineOee } from './MachineOee'
import { FileDetailCard } from './FileDetailCard'
import { KlipperConfigPanel } from './KlipperConfigPanel'
import { ExcludeObjectsMap, hasPolygonData } from '../ExcludeObjectsMap'
import { OverviewGraphs } from './OverviewGraphs'
import { MaterialSelector } from './MaterialSelector'
import type { Material } from '../types/material'
import { apiFetch } from '../api'
import { debug } from '../logging'

const OverviewDrawer = React.memo(function OverviewDrawer({
  printerId,
  printer,
  currentPrinter,
  diagnostics,
  canWrite,
  dashboardSettings,
  oeeByDevice,
  currentMetric,
  currentFileDetail,
  cvAnomalies,
  spoolLogOpen = false,
  setSpoolLogOpen = () => {},
  spoolLog = [],
  spoolLogLoading = false,
  excludeObjects,
  quickMaterial = '',
  setQuickMaterial = () => {},
  quickRemaining = 0,
  setQuickRemaining = () => {},
  quickFilamentSaving = false,
  saveQuickFilamentWithLog = async () => {},
  spoolEstimating = false,
  estimateSpoolFromPhoto = async () => {},
  spoolEstimateResult,
  formatDuration = (ms?: number | null) => String(ms ?? '—'),
  formatMillimeters = (mm?: number | null) => String(mm ?? '—'),
  formatTimestamp = (ts?: number | null) => String(ts ?? '—'),
  fetchSpoolLog = async () => {},
  capabilityOverviewItems,
  setConfirmState = () => {},
  loadExcludeObjects = async () => {},
  doExcludeObject = async () => {},
}: DrawerProps) {
  const [spoolEstimate, setSpoolEstimate] = useState<any>(null)

  if (!diagnostics) {
    return (
      <section className="drawer-section">
        <div className="subtle">Loading overview…</div>
      </section>
    )
  }

  return (
    <>
      {dashboardSettings?.show_oee && currentPrinter && oeeByDevice?.get(currentPrinter.id) && (
        <section className="drawer-section">
          <MachineOee variant="full" oee={oeeByDevice.get(currentPrinter.id)} />
        </section>
      )}

      <OverviewGraphs currentMetric={currentMetric} printerId={printerId} />

      <section className="drawer-section">
        <h3>State</h3>
        <div className="kv-grid">
          <div><span>Status</span><strong>{diagnostics.state}</strong></div>
          <div><span>Klippy connected</span><strong>{String(diagnostics.klippy_connected)}</strong></div>
          <div><span>Moonraker</span><strong>{diagnostics.moonraker_version || '—'}</strong></div>
          <div><span>API</span><strong>{diagnostics.api_version_string || '—'}</strong></div>
          <div><span>PID</span><strong>{diagnostics.process_id ?? '—'}</strong></div>
          <div><span>Attention</span><strong>{diagnostics.attention_needed ? 'Yes' : 'No'}</strong></div>
        </div>
      </section>

      <section className="drawer-section">
        <h3>Current file</h3>
        {currentFileDetail?.detail ? (
          <FileDetailCard detail={currentFileDetail.detail} />
        ) : (
          <div className="subtle">No active or selected file.</div>
        )}
      </section>

      <section className="drawer-section">
        <h3>Printer metrics</h3>
        <div className="kv-grid">
          <div><span>Success rate</span><strong>{currentMetric?.success_rate == null ? '—' : `${currentMetric.success_rate.toFixed(1)}%`}</strong></div>
          <div><span>Completed</span><strong>{currentMetric?.completed_jobs ?? 0}</strong></div>
          <div><span>Failed</span><strong>{currentMetric?.failed_jobs ?? 0}</strong></div>
          <div><span>Cancelled</span><strong>{currentMetric?.cancelled_jobs ?? 0}</strong></div>
          <div><span>Total print time</span><strong>{formatDuration(currentMetric?.total_print_time)}</strong></div>
          <div><span>Filament used</span><strong>{formatMillimeters(currentMetric?.total_filament_used)}</strong></div>
          <div><span>Average print</span><strong>{formatDuration(currentMetric?.avg_print_time)}</strong></div>
          <div><span>Last job</span><strong>{formatTimestamp(currentMetric?.last_job_end_time)}</strong></div>
        </div>
      </section>

      {printerId && cvAnomalies && cvAnomalies[printerId]?.length > 0 && (
        <section className="drawer-section">
          <h3>CV Monitor</h3>
          <div style={{display:'flex', flexDirection:'column', gap:6}}>
            {[...(printerId && cvAnomalies[printerId] ? cvAnomalies[printerId] : [])].reverse().slice(0, 5).map((a: any, i: number) => (
              <div key={i} className="subtle small" style={{display:'flex', gap:8, alignItems:'center'}}>
                <span style={{color: a.confidence === 'high' ? 'var(--color-error, #e53)' : 'var(--color-warning, #f90)'}}>
                  ⚠ {a.type.replace(/_/g, ' ')}
                </span>
                <span>{Math.round(a.score * 100)}%</span>
                <span className="subtle">{a.reasoning}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="drawer-section">
        <h3>Filament & Materials</h3>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {canWrite && (
            <MaterialSelector
              onApply={(materialName: string) => {
                setQuickMaterial(materialName)
                // Material details are for reference; actual temperature/speed application
                // would require printer API endpoints (not yet available)
              }}
              currentMaterial={quickMaterial}
              disabled={!canWrite}
            />
          )}
        </div>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          {canWrite && (
            <div style={{display:'flex', gap:8, alignItems:'center', flexWrap:'wrap'}}>
              <input
                type="text"
                placeholder="Material (e.g. PLA)"
                value={quickMaterial}
                onChange={e => setQuickMaterial(e.target.value)}
                style={{flex:'1 1 100px', minWidth:80}}
              />
              <input
                type="number"
                placeholder="Remaining (g)"
                value={quickRemaining}
                onChange={e => setQuickRemaining(parseInt(e.target.value) || 0)}
                style={{flex:'1 1 80px', minWidth:70}}
                min={0}
              />
              <button onClick={() => void saveQuickFilamentWithLog?.(quickRemaining)} disabled={quickFilamentSaving} className="action-btn">
                {quickFilamentSaving ? 'Saving…' : 'Update'}
              </button>
            </div>
          )}
          {canWrite && (
            <div style={{display:'flex', gap:8, alignItems:'center'}}>
              <label className="action-btn" style={{cursor:'pointer', opacity: spoolEstimating ? 0.6 : 1}}>
                {spoolEstimating ? '⏳ Estimating…' : '📷 Estimate from photo'}
                <input
                  type="file"
                  accept="image/*"
                  capture="environment"
                  style={{display:'none'}}
                  disabled={spoolEstimating}
                  onChange={e => { const f = e.target.files?.[0]; if (f) void estimateSpoolFromPhoto?.(f); e.target.value = '' }}
                />
              </label>
              {spoolEstimateResult && (
                <span className="subtle small">
                  {Math.round(spoolEstimateResult.fill_pct * 100)}% · {spoolEstimateResult.confidence} · {spoolEstimateResult.model_used}
                </span>
              )}
            </div>
          )}
          {spoolEstimateResult?.reasoning && (
            <div className="subtle small" style={{fontStyle:'italic'}}>{spoolEstimateResult.reasoning}</div>
          )}
          {diagnostics.capability.spool_remaining_g != null && (
            <div className="subtle small">{diagnostics.capability.spool_remaining_g}g remaining · {diagnostics.capability.current_material || 'no material set'}</div>
          )}
          <div style={{marginTop:8}}>
            <button
              className="action-btn"
              style={{fontSize:'0.8rem', padding:'3px 10px'}}
              onClick={() => { setSpoolLogOpen?.(!spoolLogOpen); if (!spoolLogOpen && printerId) void fetchSpoolLog?.(printerId) }}
            >
              {spoolLogOpen ? '▴ Hide log' : '▾ Depletion log'}{spoolLog.length > 0 ? ` (${spoolLog.length})` : ''}
            </button>
            {spoolLogOpen && (
              <div style={{marginTop:6, overflowX:'auto'}}>
                {spoolLogLoading ? (
                  <span className="subtle small">Loading…</span>
                ) : spoolLog.length === 0 ? (
                  <span className="subtle small">No entries yet — deductions are recorded automatically on job completion.</span>
                ) : (
                  <table style={{width:'100%', fontSize:'0.78rem', borderCollapse:'collapse'}}>
                    <thead>
                      <tr style={{opacity:0.55}}>
                        <th style={{textAlign:'left', paddingBottom:4}}>Date</th>
                        <th style={{textAlign:'left', paddingBottom:4}}>Job</th>
                        <th style={{textAlign:'right', paddingBottom:4}}>Used (g)</th>
                        <th style={{textAlign:'right', paddingBottom:4}}>After (g)</th>
                        <th style={{textAlign:'left', paddingBottom:4}}>Src</th>
                      </tr>
                    </thead>
                    <tbody>
                      {spoolLog.map((entry: any) => (
                        <tr key={entry.id} style={{borderTop:'1px solid var(--color-border, #333)'}}>
                          <td style={{padding:'3px 6px 3px 0', whiteSpace:'nowrap'}}>
                            {entry.created_at ? new Date(entry.created_at).toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—'}
                          </td>
                          <td style={{padding:'3px 6px', maxWidth:140, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}} title={entry.job_name ?? undefined}>
                            {entry.job_name ?? <span style={{opacity:0.4}}>—</span>}
                          </td>
                          <td style={{textAlign:'right', padding:'3px 6px', color: (entry.filament_used_g ?? 0) > 0 ? 'var(--color-warning, #f90)' : undefined}}>
                            {entry.filament_used_g != null ? `-${entry.filament_used_g}` : '—'}
                          </td>
                          <td style={{textAlign:'right', padding:'3px 6px', fontWeight:600}}>
                            {entry.spool_after_g ?? '—'}
                          </td>
                          <td style={{padding:'3px 0 3px 6px', opacity:0.5}}>
                            {entry.source === 'manual' ? '✏' : '⚙'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="drawer-section">
        <h3>Capability profile</h3>
        <div className="kv-grid">
          {capabilityOverviewItems?.(diagnostics.capability, diagnostics.homed_axes, dashboardSettings?.show_empty_capability_tiles).map((item: any) => (
            <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>
          ))}
        </div>
      </section>

      {diagnostics.klipper_config && (
        <section className="drawer-section">
          <h3>Hardware config <span className="subtle small">(printer.cfg)</span></h3>
          <KlipperConfigPanel cfg={diagnostics.klipper_config} />
        </section>
      )}

      <section className="drawer-section">
        <h3>Suggested checks</h3>
        <ul>{diagnostics.suggested_checks.map((item: string) => <li key={item}>{item}</li>)}</ul>
      </section>

      <section className="drawer-section">
        <h3>Paths</h3>
        <div className="path-list">
          <code>{diagnostics.config_file || '—'}</code>
          <code>{diagnostics.log_file || '—'}</code>
        </div>
      </section>

      <section className="drawer-section">
        <h3>Recent log lines</h3>
        <pre className="log-box">{diagnostics.recent_log_lines.length > 0 ? diagnostics.recent_log_lines.join('\n') : 'No log lines available to the service user.'}</pre>
      </section>

      {currentPrinter?.state === 'printing' && (
        <section className="drawer-section">
          <h3>Exclude objects</h3>
          {excludeObjects === null && (
            <button onClick={() => void loadExcludeObjects()} className="action-btn">Load objects</button>
          )}
          {excludeObjects && excludeObjects !== null && !excludeObjects.supported && (
            <div className="subtle">Not available. Add <code>[exclude_object]</code> to printer.cfg to enable.</div>
          )}
          {excludeObjects?.supported && (
            <>
              {excludeObjects.objects.length === 0 && <div className="subtle">No named objects in current print.</div>}
              {hasPolygonData(excludeObjects.objects) ? (
                <ExcludeObjectsMap
                  objects={excludeObjects.objects}
                  excluded={excludeObjects.excluded}
                  currentObject={excludeObjects.current_object}
                  canWrite={canWrite ?? false}
                  onExclude={(name) => setConfirmState({message: `Exclude "${name}" from print?`, onConfirm: () => void doExcludeObject(name)})}
                />
              ) : (
                <div style={{display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4}}>
                  {excludeObjects.objects.map((obj: any) => {
                    const isExcluded = excludeObjects.excluded.includes(obj.name)
                    const isCurrent = excludeObjects.current_object === obj.name
                    return (
                      <button
                        key={obj.name}
                        onClick={() => canWrite && !isExcluded && setConfirmState({message: `Exclude "${obj.name}" from print?`, onConfirm: () => void doExcludeObject(obj.name)})}
                        style={{
                          opacity: isExcluded ? 0.45 : 1,
                          textDecoration: isExcluded ? 'line-through' : 'none',
                          border: isCurrent ? '1px solid var(--accent-solid)' : undefined,
                          cursor: isExcluded || !(canWrite ?? false) ? 'default' : 'pointer',
                          fontSize: 11,
                        }}
                        disabled={isExcluded || !(canWrite ?? false)}
                        title={isExcluded ? 'Already excluded' : !(canWrite ?? false) ? 'Requires operator or admin role' : `Exclude ${obj.name}`}
                      >
                        {obj.name}{isCurrent ? ' ●' : ''}
                      </button>
                    )
                  })}
                </div>
              )}
              <button onClick={() => void loadExcludeObjects()} style={{marginTop: 8, fontSize: 11}} className="action-btn">Refresh</button>
            </>
          )}
        </section>
      )}
    </>
  )
})

export default OverviewDrawer
