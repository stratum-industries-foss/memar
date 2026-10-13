import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mocked before the import of FleetTools so HealthPanel's useJson picks it up.
const apiFetch = vi.fn()
vi.mock('../api', () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }))

const { HealthPanel } = await import('../FleetTools')
const { ErrorBoundary } = await import('../ErrorBoundary')

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => body, text: async () => '' })
}

/**
 * Moonraker's /machine/proc_stats reports `system_cpu_usage` as a PER-CORE
 * OBJECT — {"cpu": 9.76, "cpu0": 8.91, ...} — not a scalar. The backend used to
 * forward it verbatim as `cpu_usage`, so HealthPanel's `cpu_usage.toFixed(1)`
 * threw a TypeError *during render*. Because the only ErrorBoundary in the app
 * wraps all of <App/> (main.tsx), that single bad field replaced the entire
 * dashboard with "Something went wrong" and the user had to reload the page.
 *
 * fleet.fetch_host_stats now unwraps the dict to its "cpu" aggregate, and the
 * component typeof-guards the value as defence in depth. This test pins the
 * component half: a non-numeric field must degrade to "—", never throw.
 */
describe('HealthPanel — non-numeric host stats must not crash the dashboard', () => {
  beforeEach(() => {
    apiFetch.mockReset()
  })

  function mockHostStats(cpuUsage: unknown, cpuTemp: unknown = 70.2) {
    apiFetch.mockImplementation((url: string) => {
      if (url.includes('/host-stats')) {
        return jsonOk({
          cpu_temp: cpuTemp,
          cpu_usage: cpuUsage,
          memory_used_mb: 2551.4,
          memory_total_mb: 15707.3,
          uptime_s: 1256477,
          network_rx_mb: 0,
          network_tx_mb: 0,
          websocket_count: 2,
        })
      }
      if (url.includes('/updates')) return jsonOk({ components: [], system_packages_pending: 0 })
      return jsonOk({})
    })
  }

  it('renders the real Moonraker per-core dict as "—" instead of throwing', async () => {
    mockHostStats({ cpu: 9.76, cpu0: 8.91, cpu1: 5.0 })

    render(
      <ErrorBoundary>
        <HealthPanel printerId="printer-1" />
      </ErrorBoundary>,
    )

    // Uptime proves the panel actually rendered its stat grid...
    expect(await screen.findByText('14d 13h')).toBeInTheDocument()
    // ...and the boundary was never tripped.
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  it('still formats a well-formed numeric cpu_usage', async () => {
    mockHostStats(9.76)

    render(<HealthPanel printerId="printer-1" />)

    expect(await screen.findByText('9.8%')).toBeInTheDocument()
    expect(await screen.findByText('70.2 °C')).toBeInTheDocument()
  })

  it('survives a non-numeric cpu_temp too (same firmware-variance class)', async () => {
    mockHostStats(9.76, { core: 70.2 })

    render(
      <ErrorBoundary>
        <HealthPanel printerId="printer-1" />
      </ErrorBoundary>,
    )

    expect(await screen.findByText('9.8%')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument(),
    )
  })
})
