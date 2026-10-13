import React from 'react'
import type { DrawerProps } from '../types/drawer-props'
import { useSettingsState } from './useSettingsState'
import { ConfirmDialog } from '../ConfirmDialog'

const SettingsDrawer = React.memo(function SettingsDrawer({
  printerId,
  currentPrinter,
  canWrite,
  onMessage,
}: DrawerProps) {
  const {
    settingsDraft,
    settingsMessage,
    isSaving,
    subscription,
    showCancelConfirm,
    settingsNozzle,
    setSettingsNozzle,
    setShowCancelConfirm,
    cancelSubscription,
    updateSettingsDraft,
    updateUiTargetDraft,
    addUiTargetDraft,
    removeUiTargetDraft,
    saveNozzleDiameter,
    savePrinterSettings,
  } = useSettingsState(printerId, currentPrinter, undefined, onMessage)

  if (!settingsDraft) return null

  return (
    <>
      {/* Current Plan subscription card */}
      <div style={{ background: 'var(--surface-l2)', border: '1px solid var(--border-default)', borderRadius: 8, padding: '16px 20px', marginBottom: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 10, color: 'var(--text-primary)' }}>Current Plan</div>
        {subscription && subscription.status !== 'none' ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{ background: '#2563eb', color: '#fff', borderRadius: 4, padding: '2px 10px', fontWeight: 700, fontSize: '0.82rem', letterSpacing: '0.05em' }}>{subscription.tier.toUpperCase()}</span>
              <span style={{
                color: subscription.cancel_at_period_end ? 'var(--color-warning)' : subscription.status === 'active' ? 'var(--color-success)' : 'var(--color-danger)',
                fontSize: '0.85rem',
                fontWeight: 500,
              }}>
                {subscription.cancel_at_period_end ? '⚠ Cancels at period end' : subscription.status === 'active' ? '✓ Active' : '✗ Expired'}
              </span>
            </div>
            {subscription.expires_at && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginBottom: 6 }}>
                Expires: {new Date(subscription.expires_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </div>
            )}
            {subscription.device_limit && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginBottom: 10 }}>Up to {subscription.device_limit} devices</div>
            )}
            {subscription.status === 'active' && !subscription.cancel_at_period_end && (
              <>
                {showCancelConfirm && (
                  <ConfirmDialog
                    message="Cancel your subscription? It stays active until the end of the billing period."
                    onConfirm={() => void cancelSubscription()}
                    onCancel={() => setShowCancelConfirm(false)}
                  />
                )}
                <button
                  style={{ background: 'transparent', border: '1px solid var(--color-danger)', color: 'var(--color-danger)', borderRadius: 4, padding: '5px 14px', cursor: 'pointer', fontSize: '0.82rem' }}
                  disabled={isSaving}
                  aria-label="Cancel subscription"
                  onClick={() => setShowCancelConfirm(true)}
                >
                  {isSaving ? 'Cancelling...' : 'Cancel Subscription'}
                </button>
              </>
            )}
          </>
        ) : (
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Free tier — no active subscription.</div>
        )}
      </div>

      {/* Quick settings section */}
      <section className="drawer-section">
        <h3>Quick settings</h3>
        <div className="preset-row drawer-preset-row">
          {[0.25, 0.4, 0.6, 0.8, 1.0].map((preset) => (
            <button
              key={preset}
              onClick={() => {
                setSettingsNozzle(String(preset))
                updateSettingsDraft({ nozzleDiameter: preset.toFixed(2) })
              }}
            >
              {preset.toFixed(2)} mm
            </button>
          ))}
        </div>
        <div className="settings-grid two-col">
          <label>
            <span>Printer name</span>
            <input value={settingsDraft.name} onChange={(event) => updateSettingsDraft({ name: event.target.value })} />
          </label>
          <label>
            <span>Configured nozzle (mm)</span>
            <input
              type="number"
              step="0.01"
              value={settingsDraft.nozzleDiameter}
              onChange={(event) => {
                setSettingsNozzle(event.target.value)
                updateSettingsDraft({ nozzleDiameter: event.target.value })
              }}
            />
          </label>
          <label>
            <span>Filament diameter (mm)</span>
            <input type="number" step="0.01" placeholder="1.75" value={settingsDraft.filamentDiameterMm} onChange={(event) => updateSettingsDraft({ filamentDiameterMm: event.target.value })} />
          </label>
          <label>
            <span>Wire per job (mm) — EDM only</span>
            <input type="number" step="1" placeholder="e.g. 50000" value={settingsDraft.wireUsedMmPerJob} onChange={(event) => updateSettingsDraft({ wireUsedMmPerJob: event.target.value })} />
          </label>
        </div>
        <div className="inline-actions settings-actions-row">
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.enabled} onChange={(event) => updateSettingsDraft({ enabled: event.target.checked })} /> Enabled
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.maintenanceDue} onChange={(event) => updateSettingsDraft({ maintenanceDue: event.target.checked })} /> Maintenance due
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.maintenanceLockout} onChange={(event) => updateSettingsDraft({ maintenanceLockout: event.target.checked })} /> Maintenance lockout
          </label>
          {canWrite && <button onClick={() => void saveNozzleDiameter()} disabled={isSaving}>Save nozzle only</button>}
          {canWrite && <button onClick={() => void savePrinterSettings()} disabled={isSaving}>Save printer settings</button>}
        </div>
        <div className="subtle small">Nozzle changes should now propagate to the card, profile label, current-file compatibility view, and saved config.</div>
        <div className="action-message" aria-live="polite" aria-atomic="true">
          {settingsMessage}
        </div>
      </section>

      {/* Identity and material section */}
      <section className="drawer-section">
        <h3>Identity and material</h3>
        <div className="settings-grid three-col">
          <label>
            <span>Tags</span>
            <input value={settingsDraft.tagsText} onChange={(event) => updateSettingsDraft({ tagsText: event.target.value })} placeholder="klipper, core, 0.6nozzle" />
          </label>
          <label>
            <span>Profile</span>
            <input value={settingsDraft.compatibilityProfile} onChange={(event) => updateSettingsDraft({ compatibilityProfile: event.target.value })} placeholder="octopus-350" />
          </label>
          <label>
            <span>Supported materials</span>
            <input value={settingsDraft.supportedMaterialsText} onChange={(event) => updateSettingsDraft({ supportedMaterialsText: event.target.value })} placeholder="PLA, PETG, ASA" />
          </label>
          <label>
            <span>Current material</span>
            <input value={settingsDraft.currentMaterial} onChange={(event) => updateSettingsDraft({ currentMaterial: event.target.value })} />
          </label>
          <label>
            <span>Current spool</span>
            <input value={settingsDraft.currentSpoolName} onChange={(event) => updateSettingsDraft({ currentSpoolName: event.target.value })} />
          </label>
          <label>
            <span>Spool remaining (g)</span>
            <input type="number" value={settingsDraft.spoolRemainingG} onChange={(event) => updateSettingsDraft({ spoolRemainingG: event.target.value })} />
          </label>
          <label>
            <span>Full spool capacity (g)</span>
            <input type="number" value={settingsDraft.spoolCapacityG} onChange={(event) => updateSettingsDraft({ spoolCapacityG: event.target.value })} placeholder="1000" />
          </label>
        </div>
      </section>

      {/* Hardware and behavior section */}
      <section className="drawer-section">
        <h3>Hardware and behavior</h3>
        <div className="settings-grid three-col">
          <label>
            <span>Build volume X</span>
            <input type="number" value={settingsDraft.buildVolumeX} onChange={(event) => updateSettingsDraft({ buildVolumeX: event.target.value })} />
          </label>
          <label>
            <span>Build volume Y</span>
            <input type="number" value={settingsDraft.buildVolumeY} onChange={(event) => updateSettingsDraft({ buildVolumeY: event.target.value })} />
          </label>
          <label>
            <span>Build volume Z</span>
            <input type="number" value={settingsDraft.buildVolumeZ} onChange={(event) => updateSettingsDraft({ buildVolumeZ: event.target.value })} />
          </label>
          <label>
            <span>Safe nozzle max (C)</span>
            <input type="number" value={settingsDraft.safeNozzleMaxC} onChange={(event) => updateSettingsDraft({ safeNozzleMaxC: event.target.value })} />
          </label>
          <label>
            <span>Safe bed max (C)</span>
            <input type="number" value={settingsDraft.safeBedMaxC} onChange={(event) => updateSettingsDraft({ safeBedMaxC: event.target.value })} />
          </label>
          <label>
            <span>Timelapse dir</span>
            <input value={settingsDraft.timelapseDir} onChange={(event) => updateSettingsDraft({ timelapseDir: event.target.value })} />
          </label>
        </div>
        <div className="inline-actions settings-actions-row">
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.probe} onChange={(event) => updateSettingsDraft({ probe: event.target.checked })} /> Probe installed
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.filamentSensor} onChange={(event) => updateSettingsDraft({ filamentSensor: event.target.checked })} /> Filament sensor
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.webcamExpected} onChange={(event) => updateSettingsDraft({ webcamExpected: event.target.checked })} /> Webcam expected
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.jogEnabled} onChange={(event) => updateSettingsDraft({ jogEnabled: event.target.checked })} /> Jog enabled
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={settingsDraft.motionCheckRequired} onChange={(event) => updateSettingsDraft({ motionCheckRequired: event.target.checked })} /> Motion check required
          </label>
        </div>
      </section>

      {/* Maintenance section */}
      <section className="drawer-section">
        <h3>Maintenance</h3>
        <div className="settings-grid three-col">
          <label>
            <span>Maintenance state</span>
            <input value={settingsDraft.maintenanceState} onChange={(event) => updateSettingsDraft({ maintenanceState: event.target.value })} placeholder="ok / due / service" />
          </label>
          <label>
            <span>Next service due</span>
            <input value={settingsDraft.nextServiceDue} onChange={(event) => updateSettingsDraft({ nextServiceDue: event.target.value })} placeholder="2026-05-01" />
          </label>
          <label>
            <span>Last service</span>
            <input value={settingsDraft.lastServiceAt} onChange={(event) => updateSettingsDraft({ lastServiceAt: event.target.value })} placeholder="2026-04-10" />
          </label>
          <label>
            <span>Interval hours</span>
            <input type="number" value={settingsDraft.maintenanceIntervalHours} onChange={(event) => updateSettingsDraft({ maintenanceIntervalHours: event.target.value })} />
          </label>
          <label>
            <span>Interval jobs</span>
            <input type="number" value={settingsDraft.maintenanceIntervalJobs} onChange={(event) => updateSettingsDraft({ maintenanceIntervalJobs: event.target.value })} />
          </label>
          <label>
            <span>Interval filament (g)</span>
            <input type="number" value={settingsDraft.maintenanceIntervalFilamentG} onChange={(event) => updateSettingsDraft({ maintenanceIntervalFilamentG: event.target.value })} />
          </label>
        </div>
        <div className="settings-grid two-col">
          <label>
            <span>Operator notes</span>
            <textarea value={settingsDraft.notesText} onChange={(event) => updateSettingsDraft({ notesText: event.target.value })} rows={4} />
          </label>
          <label>
            <span>Maintenance notes</span>
            <textarea value={settingsDraft.maintenanceNotesText} onChange={(event) => updateSettingsDraft({ maintenanceNotesText: event.target.value })} rows={4} />
          </label>
        </div>
      </section>

      {/* UI and integrations section */}
      <details className="drawer-section collapsible-panel" open>
        <summary>UI and integrations</summary>
        <div className="details-body">
          <div className="settings-grid two-col">
            <label>
              <span>UI button label</span>
              <input value={settingsDraft.uiLabel} onChange={(event) => updateSettingsDraft({ uiLabel: event.target.value })} />
            </label>
            <label>
              <span>Camera URL</span>
              <input value={settingsDraft.cameraUrl} onChange={(event) => updateSettingsDraft({ cameraUrl: event.target.value })} />
            </label>
          </div>
          <div className="settings-targets">
            {settingsDraft.uiTargets.map((target, index) => (
              <div key={index} className="settings-target-row">
                <input value={target.label} onChange={(event) => updateUiTargetDraft(index, { label: event.target.value })} placeholder="Label" />
                <input value={target.provider} onChange={(event) => updateUiTargetDraft(index, { provider: event.target.value })} placeholder="Provider" />
                <input value={target.url} onChange={(event) => updateUiTargetDraft(index, { url: event.target.value })} placeholder="URL" />
                <select value={target.mode} onChange={(event) => updateUiTargetDraft(index, { mode: event.target.value as 'direct' | 'bootstrap' })}>
                  <option value="direct">direct</option>
                  <option value="bootstrap">bootstrap</option>
                </select>
                <label className="checkbox-line compact-check">
                  <input
                    type="checkbox"
                    checked={target.primary}
                    onChange={(event) => {
                      const uiTargets = settingsDraft.uiTargets.map((item, itemIndex) => ({
                        ...item,
                        primary: itemIndex === index ? event.target.checked : false,
                      }))
                      if (uiTargets.length > 0 && !uiTargets.some((item) => item.primary)) {
                        uiTargets[0] = { ...uiTargets[0], primary: true }
                      }
                      updateSettingsDraft({ uiTargets })
                    }}
                  />{' '}
                  Primary
                </label>
                <button onClick={() => removeUiTargetDraft(index)}>Remove</button>
              </div>
            ))}
            <button onClick={addUiTargetDraft}>Add UI target</button>
          </div>
        </div>
      </details>

      {/* Advanced connection settings section */}
      <details className="drawer-section collapsible-panel">
        <summary>Advanced connection settings</summary>
        <div className="details-body settings-grid two-col">
          <label>
            <span>Base URL</span>
            <input value={settingsDraft.baseUrl} onChange={(event) => updateSettingsDraft({ baseUrl: event.target.value })} />
          </label>
          <label>
            <span>WebSocket URL</span>
            <input value={settingsDraft.wsUrl} onChange={(event) => updateSettingsDraft({ wsUrl: event.target.value })} />
          </label>
          <label>
            <span>Auth mode</span>
            <input value={settingsDraft.authMode} onChange={(event) => updateSettingsDraft({ authMode: event.target.value })} />
          </label>
          <label>
            <span>Serial</span>
            <input value={settingsDraft.serial} onChange={(event) => updateSettingsDraft({ serial: event.target.value })} placeholder="Bambu printer serial (MQTT)" />
          </label>
          <label>
            <span>Access code{settingsDraft.apiKeySet ? ' (configured)' : ''}</span>
            <input
              type="password"
              autoComplete="new-password"
              value={settingsDraft.apiKey}
              disabled={settingsDraft.apiKeyClear}
              onChange={(event) => updateSettingsDraft({ apiKey: event.target.value })}
              placeholder={settingsDraft.apiKeyClear ? 'Will be removed on save' : settingsDraft.apiKeySet ? 'Leave blank to keep current' : 'Bambu LAN access code / API key'}
            />
          </label>
          {settingsDraft.apiKeySet && (
            <label className="checkbox-line">
              <input type="checkbox" checked={settingsDraft.apiKeyClear} onChange={(event) => updateSettingsDraft({ apiKeyClear: event.target.checked })} /> Clear access code
            </label>
          )}
          <label>
            <span>Fluidd fallback URL</span>
            <input value={settingsDraft.fluiddUrl} onChange={(event) => updateSettingsDraft({ fluiddUrl: event.target.value })} />
          </label>
        </div>
      </details>
    </>
  )
})

export default SettingsDrawer
