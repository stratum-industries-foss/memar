import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, apiFetch: vi.fn() }
})

import { SetupWizard } from '../SetupWizard'
import { apiFetch } from '../api'

const mockedFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

type Route = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | Promise<{ status?: number; body?: unknown }>

const respond = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: String(status),
  json: async () => body,
})

// Route apiFetch by URL. Unlisted URLs get an empty 200 JSON object.
const useRoutes = (routes: Record<string, Route>) => {
  mockedFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const key = Object.keys(routes).find((k) => String(url).startsWith(k))
    if (!key) return respond(200, {})
    const out = await routes[key](String(url), init)
    return respond(out.status ?? 200, out.body ?? {})
  })
}

const klipperResults = [
  { ip: '192.168.1.70', port: 7125, protocol: 'moonraker', name: 'voron-a', already_added: false, suggested_id: 'klipper-192-168-1-70-7125' },
  { ip: '192.168.1.71', port: 7125, protocol: 'moonraker', name: 'voron-b', already_added: false, suggested_id: 'klipper-192-168-1-71-7125' },
  { ip: '192.168.1.72', port: 7125, protocol: 'moonraker', name: 'voron-c', already_added: false, suggested_id: 'klipper-192-168-1-72-7125' },
]

const scanMeta = {
  subnet: '192.168.1.0/24',
  subnet_source: 'detected',
  in_container: false,
  scan_capped: false,
  duration_ms: 12,
}

describe('SetupWizard v2', () => {
  beforeEach(() => {
    mockedFetch.mockReset()
  })

  it('test connection shows success when the backend returns ok:true', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: [] } }),
      '/api/onboarding/test-connection': () => ({ body: { ok: true, success: true, message: 'Reached Klipper', name: 'voron-a' } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add device manually' }))
    fireEvent.change(screen.getByPlaceholderText('http://192.168.1.100:7125'), {
      target: { value: 'http://192.168.1.70:7125' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))

    const msg = await screen.findByText('Reached Klipper')
    expect(msg).toBeInTheDocument()
    expect(screen.queryByText('Connection failed')).toBeNull()
    // Friendly name from the test result pre-fills the device name.
    expect(screen.getByPlaceholderText('My Printer')).toHaveValue('voron-a')
  })

  it('test connection shows the failure message when ok is false', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: [] } }),
      '/api/onboarding/test-connection': () => ({ body: { ok: false, success: false, message: 'Refused' } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add device manually' }))
    fireEvent.change(screen.getByPlaceholderText('http://192.168.1.100:7125'), {
      target: { value: 'http://192.168.1.70:7125' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText('Refused')).toBeInTheDocument()
  })

  it('adds three Klipper devices with one POST each and no id field', async () => {
    const addCalls: Array<Record<string, unknown>> = []
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: klipperResults } }),
      '/api/license/status': () => ({ body: { tier: 'pro', device_limit: 10 } }),
      '/api/printers/add': (_url, init) => {
        addCalls.push(JSON.parse(init!.body as string))
        return { body: { success: true, id: 'generated' } }
      },
      '/api/printers': () => ({ body: [] }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)

    // Klipper devices found by the scan are ticked already: one click adds them all.
    expect(await screen.findByLabelText('Select voron-a')).toBeChecked()
    expect(screen.getByLabelText('Select voron-c')).toBeChecked()
    fireEvent.click(await screen.findByRole('button', { name: 'Add selected (3)' }))

    expect(await screen.findByText('3 devices added')).toBeInTheDocument()
    const adds = mockedFetch.mock.calls.filter((c) => String(c[0]).includes('/api/printers/add'))
    expect(adds.length).toBe(3)
    expect(addCalls.map((b) => b.name)).toEqual(['voron-a', 'voron-b', 'voron-c'])
    for (const body of addCalls) {
      expect(body).not.toHaveProperty('id')
      expect(body.protocol).toBe('moonraker')
    }
  })

  it('shows protocol as a friendly label, with the port only when one host runs several', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: [klipperResults[0]] } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    expect(await screen.findByText('Klipper / Moonraker · 192.168.1.70')).toBeInTheDocument()
    expect(screen.getByText('Found 1 device on your network. The ticked ones will be added.')).toBeInTheDocument()
  })

  it('shows ports for several instances on one host', async () => {
    const sameHost = [7125, 7126].map((port, i) => ({
      ip: '192.168.1.70', port, protocol: 'moonraker', name: `ender-${i + 1}`, already_added: false, suggested_id: `k-${port}`,
    }))
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: sameHost } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    expect(await screen.findByText(/Klipper \/ Moonraker · 192\.168\.1\.70:7126/)).toBeInTheDocument()
  })

  it('caps selection at the remaining device slots and explains the plan limit', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: klipperResults } }),
      '/api/license/status': () => ({ body: { tier: 'starter', device_limit: 2 } }),
      '/api/printers': () => ({ body: [] }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)

    expect(
      await screen.findByText(/Your plan monitors 2 devices\. Choose which 2 to add/),
    ).toBeInTheDocument()

    // The pre-ticked set is trimmed to the free slots; the rest wait for the user's choice.
    await waitFor(() => expect(screen.getByLabelText('Select voron-c')).toBeDisabled())
    expect(screen.getByLabelText('Select voron-a')).toBeChecked()
    expect(screen.getByLabelText('Select voron-b')).toBeChecked()
    expect(screen.getByLabelText('Select voron-c')).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Add selected (2)' })).toBeEnabled()
  })

  it('shows the fallback subnet input and rescans with ?subnet=', async () => {
    let scanUrls: string[] = []
    useRoutes({
      '/api/onboarding/scan': (url) => {
        scanUrls.push(url)
        const fallback = url.includes('subnet=')
          ? { ...scanMeta, subnet: '10.0.0.0/24', subnet_source: 'user' }
          : { ...scanMeta, subnet: '172.17.0.0/16', subnet_source: 'fallback', in_container: true }
        return { body: { ...fallback, results: [] } }
      },
    })
    render(<SetupWizard isOpen onClose={() => {}} />)

    const input = await screen.findByLabelText('Search another network')
    // People type the first three numbers; the wizard turns it into a /24.
    fireEvent.change(input, { target: { value: '10.0.0.x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search this network' }))

    await waitFor(() => expect(scanUrls.length).toBe(2))
    expect(decodeURIComponent(scanUrls[1])).toBe('/api/onboarding/scan?subnet=10.0.0.0/24')
  })

  it('maps a 403 scan to an admin login message', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ status: 403, body: { detail: 'forbidden' } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    expect(
      await screen.findByText('Please log in as an admin to scan your network.'),
    ).toBeInTheDocument()
  })

  it('shows the scan-incomplete note when the scan is capped', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, scan_capped: true, results: klipperResults } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    expect(await screen.findByText('Scan incomplete — add missing machines manually.')).toBeInTheDocument()
  })

  it('keeps already-added devices visible but disabled', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({
        body: { ...scanMeta, results: [{ ...klipperResults[0], already_added: true }] },
      }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    expect(await screen.findByText('Already added')).toBeInTheDocument()
    expect(screen.getByLabelText('Select voron-a')).toBeDisabled()
  })

  it('offers another network only on request when the detected one looks right', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: klipperResults } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    await screen.findByLabelText('Select voron-a')
    expect(screen.queryByLabelText('Search another network')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Printers on a different network?' }))
    expect(screen.getByLabelText('Search another network')).toBeInTheDocument()
  })

  it('turns 192.168.2.x into a subnet and leaves CIDR as typed', async () => {
    const { toSubnet } = await import('../SetupWizard')
    expect(toSubnet('192.168.2.x')).toBe('192.168.2.0/24')
    expect(toSubnet(' 192.168.2 ')).toBe('192.168.2.0/24')
    expect(toSubnet('10.0.0.0/22')).toBe('10.0.0.0/22')
  })

  it('names an unnamed OctoPrint plainly and says why it is not ticked', async () => {
    useRoutes({
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: [
        { ip: '192.168.1.80', port: 5000, protocol: 'octoprint', name: 'OctoPrint 192.168.1.80:5000', already_added: false, suggested_id: 'o' },
      ] } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    const box = await screen.findByLabelText('Select OctoPrint printer')
    expect(box).not.toBeChecked()
    expect(screen.getByText('Needs an access key. Tick to enter it.')).toBeInTheDocument()
  })

  it('partial add: the plan cap counts pending rows only and Retry failed re-posts the failed one', async () => {
    // Limit 4 with 2 already configured: 2 free slots, 3 found.
    let calls = 0
    const posted: string[] = []
    useRoutes({
      '/api/license/status': () => ({ body: { device_limit: 4 } }),
      '/api/printers/add': (_u, init) => {
        posted.push(JSON.parse(String(init?.body)).name)
        calls += 1
        return calls === 2 ? { status: 500, body: { message: 'boom' } } : { body: { success: true } }
      },
      '/api/printers': () => ({ body: [{ id: 'p1' }, { id: 'p2' }] }),
      '/api/onboarding/scan': () => ({ body: { ...scanMeta, results: klipperResults } }),
    })
    render(<SetupWizard isOpen onClose={() => {}} />)
    await waitFor(() => expect(screen.getByLabelText('Select voron-c')).toBeDisabled())
    expect(screen.getByLabelText('Select voron-a')).toBeChecked()
    expect(screen.getByLabelText('Select voron-b')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Add selected (2)' }))

    // voron-a added, voron-b failed: the failed row stays ticked and retryable.
    const retry = await screen.findByRole('button', { name: 'Retry failed (1)' })
    expect(screen.getByLabelText('Select voron-b')).toBeChecked()
    // One slot is now used by voron-a; one remains, so voron-c is still disabled.
    expect(screen.getByLabelText('Select voron-c')).toBeDisabled()
    fireEvent.click(retry)
    await waitFor(() => expect(posted).toEqual(['voron-a', 'voron-b', 'voron-b']))
    expect(await screen.findByText('2 devices added')).toBeInTheDocument()
  })
})
