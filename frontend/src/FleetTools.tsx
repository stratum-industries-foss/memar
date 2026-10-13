/**
 * FleetTools — UI for previously-dark backend endpoints.
 *
 * Drawer panels (per printer):
 *  - QueuePanel        /api/printers/{id}/queue + start/pause/resume/add/delete
 *  - MaintenancePanel  /api/printers/{id}/maintenance/complete
 *  - HealthPanel       /api/printers/{id}/host-stats + /updates + /klipper-config
 *
 * Fleet modal (tabs):
 *  - OEE               /api/oee
 *  - Firmware          /api/fleet/firmware
 *  - Webhooks          /api/alerts/webhooks CRUD
 *  - Billing           /api/billing/my-subscription + DELETE (cancel)
 */
import React, { useCallback, useEffect, useState } from 'react'
import { apiFetch } from './api'

// ---------- shared ----------

function useJson<T>(url: string | null): { data: T | null; error: string; reload: () => void; loading: boolean } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!url) return
    let cancelled = false
    setLoading(true)
    apiFetch(url)
      .then(async (res) => {
        if (cancelled) return
        if (!res.ok) { setError(`${res.status} ${await res.text().catch(() => '')}`.trim()); setData(null); return }
        setError('')
        setData(await res.json())
      })
      .catch((err) => { if (!cancelled) { setError(String(err)); setData(null) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [url, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, reload, loading }
}

function fmtPct(v: number | null | undefined): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

function fmtTs(epoch: number | string | null | undefined): string {
  if (epoch == null) return '—'
  const d = typeof epoch === 'number' ? new Date(epoch * 1000) : new Date(epoch)
  return isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

// ---------- QueuePanel ----------

type QueueJob = { job_id: string; filename: string; time_added: number }
type QueueStatus = { state: string; jobs: QueueJob[] }

export function QueuePanel({ printerId, canWrite = true }: { printerId: string; canWrite?: boolean }) {
  const { data, error, reload, loading } = useJson<QueueStatus>(`/api/printers/${printerId}/queue`)
  const { data: fileBrowser } = useJson<any>(`/api/printers/${printerId}/files?path=gcodes`)
  const [filename, setFilename] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const act = async (method: string, path: string, body?: object) => {
    setBusy(true); setMsg('')
    try {
      const res = await apiFetch(path, {
        method,
        ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
      })
      if (!res.ok) setMsg(`Failed: ${res.status} ${await res.text().catch(() => '')}`)
      else { setMsg('OK'); reload() }
    } catch (err) { setMsg(`Failed: ${err}`) }
    setBusy(false)
  }

  return (
    <section className="drawer-section">
      <h3>Print queue {data ? <span className="subtle small">· {data.state}</span> : null}</h3>
      {error && <div className="subtle">Queue unavailable: {error}</div>}
      <div className="file-toolbar">
        {canWrite && <button disabled={busy} onClick={() => void act('POST', `/api/printers/${printerId}/queue/start`)}>Start</button>}
        {canWrite && <button disabled={busy} onClick={() => void act('POST', `/api/printers/${printerId}/queue/pause`)}>Pause</button>}
        {canWrite && <button disabled={busy} onClick={() => void act('POST', `/api/printers/${printerId}/queue/resume`)}>Resume</button>}
        <button disabled={busy || loading} onClick={reload}>Refresh</button>
      </div>
      {canWrite && <div className="file-toolbar">
        <select value={filename} onChange={(e) => setFilename(e.target.value)} style={{ flex: 1 }}>
          <option value="">Select a file...</option>
          {fileBrowser?.files?.map((f: any) => (
            <option key={f.path} value={f.path}>{f.name}</option>
          ))}
        </select>
        <button disabled={busy || !filename.trim()} onClick={() => { void act('POST', `/api/printers/${printerId}/queue/add`, { filename: filename.trim() }); setFilename('') }}>Add to queue</button>
      </div>}
      {msg && <div className="subtle small">{msg}</div>}
      <div className="history-list">
        {(data?.jobs ?? []).length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">📭</div>
            <h4>Queue is empty</h4>
            <p>Add files to the queue to get started.</p>
          </div>
        )}
        {(data?.jobs ?? []).map((job) => (
          <div key={job.job_id} className="history-row">
            <div>
              <strong>{job.filename}</strong>
              <div className="subtle small">added {fmtTs(job.time_added)}</div>
            </div>
            {canWrite && <button disabled={busy} onClick={() => void act('DELETE', `/api/printers/${printerId}/queue/${encodeURIComponent(job.job_id)}`)}>Remove</button>}
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------- MaintenancePanel ----------

export function MaintenancePanel({ printerId, onDone, canWrite = true }: { printerId: string; onDone?: () => void; canWrite?: boolean }) {
  const [maintType, setMaintType] = useState('service')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const complete = async () => {
    setBusy(true); setMsg('')
    try {
      const res = await apiFetch(`/api/printers/${printerId}/maintenance/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: maintType, ...(note.trim() ? { note: note.trim() } : {}) }),
      })
      if (!res.ok) setMsg(`Failed: ${res.status} ${await res.text().catch(() => '')}`)
      else { setMsg('Maintenance recorded — service clock reset.'); setNote(''); onDone?.() }
    } catch (err) { setMsg(`Failed: ${err}`) }
    setBusy(false)
  }

  return (
    <section className="drawer-section">
      <h3>Record maintenance</h3>
      {canWrite ? (
      <div className="file-toolbar">
        <select value={maintType} onChange={(e) => setMaintType(e.target.value)}>
          {['service', 'nozzle_change', 'rebuild'].map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional note" style={{ flex: 1 }} />
        <button disabled={busy} onClick={() => void complete()}>Mark complete</button>
      </div>
      ) : <div className="subtle small">Read-only — log in as operator/admin to record maintenance.</div>}
      {msg && <div className="subtle small">{msg}</div>}
    </section>
  )
}

// ---------- HealthPanel ----------

type HostStats = {
  cpu_temp: number | null; cpu_usage: number | null
  memory_used_mb: number | null; memory_total_mb: number | null
  uptime_s: number | null; network_rx_mb: number | null; network_tx_mb: number | null
  websocket_count: number
}
type UpdateComponent = { name: string; version: string; commits_behind: number; is_dirty: boolean }
type UpdateStatus = { components: UpdateComponent[]; system_packages_pending: number }

function fmtUptime(s: number | null): string {
  if (s == null) return '—'
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

export function HealthPanel({ printerId }: { printerId: string }) {
  const host = useJson<HostStats>(`/api/printers/${printerId}/host-stats`)
  const updates = useJson<UpdateStatus>(`/api/printers/${printerId}/updates`)
  const [cfgOpen, setCfgOpen] = useState(false)
  const cfg = useJson<Record<string, unknown>>(cfgOpen ? `/api/printers/${printerId}/klipper-config` : null)

  const h = host.data
  const memPct = h?.memory_used_mb != null && h?.memory_total_mb ? (h.memory_used_mb / h.memory_total_mb) * 100 : null

  return (
    <>
      <section className="drawer-section">
        <h3>Host stats</h3>
        {host.error && <div className="subtle">Unavailable: {host.error}</div>}
        {h && (
          <div className="kv-grid">
            {/* typeof-guarded, not just null-guarded: these come straight off the
                printer's firmware, and a non-numeric value (Moonraker reports
                per-core CPU usage as an object) would throw inside render and take
                the whole dashboard down via the root ErrorBoundary. */}
            <div><span>CPU temp</span><strong>{typeof h.cpu_temp === 'number' ? `${h.cpu_temp.toFixed(1)} °C` : '—'}</strong></div>
            <div><span>CPU usage</span><strong>{typeof h.cpu_usage === 'number' ? `${h.cpu_usage.toFixed(1)}%` : '—'}</strong></div>
            <div><span>Memory</span><strong>{h.memory_used_mb != null ? `${Math.round(h.memory_used_mb)} / ${Math.round(h.memory_total_mb ?? 0)} MB${memPct != null ? ` (${memPct.toFixed(0)}%)` : ''}` : '—'}</strong></div>
            <div><span>Uptime</span><strong>{fmtUptime(h.uptime_s)}</strong></div>
            <div><span>Network RX</span><strong>{h.network_rx_mb != null ? `${h.network_rx_mb.toFixed(1)} MB` : '—'}</strong></div>
            <div><span>Network TX</span><strong>{h.network_tx_mb != null ? `${h.network_tx_mb.toFixed(1)} MB` : '—'}</strong></div>
            <div><span>WS clients</span><strong>{h.websocket_count}</strong></div>
          </div>
        )}
      </section>
      <section className="drawer-section">
        <h3>Software updates</h3>
        {updates.error && <div className="subtle">Unavailable: {updates.error}</div>}
        {updates.data && (
          <>
            {updates.data.system_packages_pending > 0 && (
              <div className="subtle small" style={{ marginBottom: 6 }}>{updates.data.system_packages_pending} system packages pending</div>
            )}
            {updates.data.components.length === 0 && <div className="subtle">No update components reported (printer offline or update manager disabled).</div>}
            {updates.data.components.length > 0 && (
              <div className="history-list">
                {updates.data.components.map((c) => (
                  <div key={c.name} className="history-row">
                    <div>
                      <strong>{c.name}</strong>
                      <div className="subtle small">{c.version}{c.is_dirty ? ' · dirty' : ''}</div>
                    </div>
                    {c.commits_behind > 0
                      ? <span className="alert-badge severity-warning">{c.commits_behind} behind</span>
                      : <span className="subtle small">up to date</span>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>
      <section className="drawer-section">
        <h3>Klipper config</h3>
        {!cfgOpen && <button onClick={() => setCfgOpen(true)}>Load parsed printer.cfg</button>}
        {cfgOpen && cfg.loading && <div className="subtle">Loading…</div>}
        {cfgOpen && cfg.error && <div className="subtle">Unavailable: {cfg.error}</div>}
        {cfgOpen && cfg.data && <pre className="log-box">{JSON.stringify(cfg.data, null, 2)}</pre>}
      </section>
    </>
  )
}

// ---------- Fleet modal ----------

type OeeDevice = { device_id: string; oee: number | null; availability: number | null; performance: number | null; quality: number | null; sample_jobs: number }
type FirmwarePrinter = { id: string; name: string; update_available: boolean; components: UpdateComponent[] }
type FirmwareSummary = { printers: FirmwarePrinter[]; update_needed: Array<{ id: string; name: string; components: string[] }>; total_printers: number }
type Webhook = { id: number; url: string; events: string[]; active: boolean; created_by: number; created_at: string }
type Subscription = { tier: string; status: string; expires_at: string | null; device_limit: number | null; cancel_at_period_end: boolean; stripe_customer_id: string | null }

function OeeTab() {
  const { data, error, loading } = useJson<{ devices: OeeDevice[] }>('/api/oee')
  if (loading) return <div className="subtle">Computing OEE…</div>
  if (error) return <div className="subtle">OEE unavailable: {error}</div>
  return (
    <div className="history-list">
      {(data?.devices ?? []).length === 0 && <div className="subtle">No devices.</div>}
      {(data?.devices ?? []).map((d) => (
        <div key={d.device_id} className="history-row">
          <div>
            <strong>{d.device_id}</strong>
            <div className="subtle small">availability {fmtPct(d.availability)} · performance {fmtPct(d.performance)} · quality {fmtPct(d.quality)} · {d.sample_jobs} jobs</div>
          </div>
          <strong>{fmtPct(d.oee)}</strong>
        </div>
      ))}
    </div>
  )
}

function FirmwareTab() {
  const { data, error, loading } = useJson<FirmwareSummary>('/api/fleet/firmware')
  if (loading) return <div className="subtle">Fetching firmware summary…</div>
  if (error) return <div className="subtle">Firmware summary unavailable: {error}</div>
  if (!data) return null
  return (
    <>
      <div className="subtle small" style={{ marginBottom: 8 }}>
        {data.total_printers} printers · {data.update_needed.length} need updates
      </div>
      <div className="history-list">
        {data.printers.length === 0 && <div className="subtle">No firmware data — printers offline or unreachable.</div>}
        {data.printers.map((p) => (
          <div key={p.id} className="history-row">
            <div>
              <strong>{p.name || p.id}</strong>
              <div className="subtle small">
                {p.components.length === 0
                  ? 'no components reported'
                  : p.components.map((c) => `${c.name} ${c.version}${c.commits_behind > 0 ? ` (${c.commits_behind} behind)` : ''}${c.is_dirty ? ' [dirty]' : ''}`).join(' · ')}
              </div>
            </div>
            {p.update_available
              ? <span className="alert-badge severity-warning">update</span>
              : <span className="subtle small">current</span>}
          </div>
        ))}
      </div>
    </>
  )
}

// Events actually dispatched by the backend (webhooks.py poll loop + main.py anomaly publisher)
const WEBHOOK_EVENTS = ['printer.error', 'printer.complete', 'printer.offline', 'printer.anomaly']

function WebhooksTab({ canWrite }: { canWrite: boolean }) {
  const { data, error, reload } = useJson<Webhook[]>('/api/alerts/webhooks/')
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState<Set<string>>(new Set(['printer.error']))
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const toggleEvent = (ev: string) => setEvents((prev) => {
    const next = new Set(prev)
    if (next.has(ev)) next.delete(ev); else next.add(ev)
    return next
  })

  const create = async () => {
    setBusy(true); setMsg('')
    try {
      const res = await apiFetch('/api/alerts/webhooks/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim(), events: [...events] }),
      })
      if (!res.ok) setMsg(`Create failed: ${res.status} ${await res.text().catch(() => '')}`)
      else { setUrl(''); setMsg('Webhook created.'); reload() }
    } catch (err) { setMsg(`Create failed: ${err}`) }
    setBusy(false)
  }

  const remove = async (id: number) => {
    setBusy(true); setMsg('')
    try {
      const res = await apiFetch(`/api/alerts/webhooks/${id}`, { method: 'DELETE' })
      if (!res.ok) setMsg(`Delete failed: ${res.status}`)
      else reload()
    } catch (err) { setMsg(`Delete failed: ${err}`) }
    setBusy(false)
  }

  return (
    <>
      {error && <div className="subtle">Webhooks unavailable: {error} (requires an active license)</div>}
      {canWrite && <div className="file-toolbar">
        <label htmlFor="webhook-url" className="sr-only">Webhook URL</label>
        <input id="webhook-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hook" style={{ flex: 1 }} />
        <button disabled={busy || !url.trim() || events.size === 0} onClick={() => void create()}>Create</button>
      </div>}
      {canWrite && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '8px 0' }}>
        {WEBHOOK_EVENTS.map((ev) => (
          <label key={ev} className="subtle small" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={events.has(ev)} onChange={() => toggleEvent(ev)} />{ev}
          </label>
        ))}
      </div>}
      {msg && <div className="subtle small">{msg}</div>}
      <div className="history-list">
        {(data ?? []).length === 0 && !error && <div className="subtle">No webhooks configured.</div>}
        {(data ?? []).map((wh) => (
          <div key={wh.id} className="history-row">
            <div>
              <strong>{wh.url}</strong>
              <div className="subtle small">{wh.events.join(', ')} · {wh.active ? 'active' : 'inactive'} · created {fmtTs(wh.created_at)}</div>
            </div>
            {canWrite && <button disabled={busy} onClick={() => void remove(wh.id)}>Delete</button>}
          </div>
        ))}
      </div>
    </>
  )
}

function BillingTab({ canWrite }: { canWrite: boolean }) {
  const { data, error, reload, loading } = useJson<Subscription>('/api/billing/my-subscription')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const cancel = async () => {
    if (!window.confirm('Cancel subscription at end of billing period?')) return
    setBusy(true); setMsg('')
    try {
      const res = await apiFetch('/api/billing/my-subscription', { method: 'DELETE' })
      if (!res.ok) setMsg(`Cancel failed: ${res.status} ${await res.text().catch(() => '')}`)
      else { setMsg('Subscription will cancel at end of billing period.'); reload() }
    } catch (err) { setMsg(`Cancel failed: ${err}`) }
    setBusy(false)
  }

  if (loading) return <div className="subtle">Loading subscription…</div>
  if (error) return <div className="subtle">No subscription found: {error}</div>
  if (!data) return null
  return (
    <>
      <div className="kv-grid">
        <div><span>Tier</span><strong>{data.tier}</strong></div>
        <div><span>Status</span><strong>{data.status}</strong></div>
        <div><span>Device limit</span><strong>{data.device_limit ?? 'unlimited'}</strong></div>
        <div><span>Expires</span><strong>{fmtTs(data.expires_at)}</strong></div>
        <div><span>Cancels at period end</span><strong>{data.cancel_at_period_end ? 'yes' : 'no'}</strong></div>
      </div>
      {canWrite && !data.cancel_at_period_end && data.status === 'active' && (
        <button disabled={busy} onClick={() => void cancel()} style={{ marginTop: 12 }}>Cancel subscription</button>
      )}
      {msg && <div className="subtle small" style={{ marginTop: 8 }}>{msg}</div>}
    </>
  )
}

type FleetToolsTab = 'oee' | 'firmware' | 'webhooks' | 'billing'

export function FleetToolsModal({ onClose, canWrite = true }: { onClose: () => void; canWrite?: boolean }) {
  const [tab, setTab] = useState<FleetToolsTab>('oee')
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" role="dialog" aria-modal="true" aria-label="Fleet tools" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 720, width: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
        <button className="modal-close" aria-label="Close fleet tools" onClick={onClose}>✕</button>
        <h2>Fleet tools</h2>
        <div className="file-toolbar" style={{ marginBottom: 12 }}>
          {(['oee', 'firmware', 'webhooks', 'billing'] as FleetToolsTab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)} style={tab === t ? { fontWeight: 700, textDecoration: 'underline' } : undefined}>
              {t === 'oee' ? 'OEE' : t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        {tab === 'oee' && <OeeTab />}
        {tab === 'firmware' && <FirmwareTab />}
        {tab === 'webhooks' && <WebhooksTab canWrite={canWrite} />}
        {tab === 'billing' && <BillingTab canWrite={canWrite} />}
      </div>
    </div>
  )
}
