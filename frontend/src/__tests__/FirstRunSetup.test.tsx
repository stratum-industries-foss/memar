import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { FirstRunSetup, normalizeSetupCode } from '../FirstRunSetup'
import type { FirstRunStatus } from '../FirstRunSetup'

const baseStatus: FirstRunStatus = {
  claimed: false,
  mode: 'auto',
  code_required: false,
  window_seconds_left: 512,
  where_is_the_code: ['Docker: run  docker logs memar', 'Linux service: run  sudo memar setup-link'],
}

const jsonResponse = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: String(status),
  json: async () => body,
})

const fillValid = (code?: string) => {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'owner' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-1' } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'correct-horse-1' } })
  if (code !== undefined) {
    fireEvent.change(screen.getByLabelText('Setup code'), { target: { value: code } })
  }
}

describe('FirstRunSetup', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, '', '/')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('claim happy path stores tokens and reports claimed', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        access_token: 'acc-1',
        refresh_token: 'ref-1',
        token_type: 'bearer',
        must_change_password: false,
      }),
    )
    const onClaimed = vi.fn()
    render(<FirstRunSetup status={baseStatus} onClaimed={onClaimed} onAlreadyClaimed={() => {}} />)

    expect(screen.getByText('Welcome to MEMAR')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toHaveValue('admin')
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))

    await waitFor(() => expect(onClaimed).toHaveBeenCalledWith('owner'))
    expect(localStorage.getItem('memar-access-token')).toBe('acc-1')
    expect(localStorage.getItem('memar-refresh-token')).toBe('ref-1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/setup/claim')
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ username: 'owner', password: 'correct-horse-1', code: null })
  })

  it('prefills the setup code from ?code= in any case and without a dash', () => {
    window.history.replaceState(null, '', '/setup?code=abcd2345')
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    expect(screen.getByLabelText('Setup code')).toHaveValue('ABCD-2345')
    expect(normalizeSetupCode('abcd-2345')).toBe('ABCD-2345')
  })

  it('clears ?code= from the URL after a successful claim', async () => {
    window.history.replaceState(null, '', '/setup?code=ABCD-2345')
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, { access_token: 'a', refresh_token: 'r', token_type: 'bearer', must_change_password: false }),
    )
    const onClaimed = vi.fn()
    render(<FirstRunSetup status={baseStatus} onClaimed={onClaimed} onAlreadyClaimed={() => {}} />)
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    await waitFor(() => expect(onClaimed).toHaveBeenCalled())
    expect(window.location.search).toBe('')
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.code).toBe('ABCD-2345')
  })

  it('reveals the code field with where-to-find hints when code_required', () => {
    render(
      <FirstRunSetup
        status={{ ...baseStatus, code_required: true }}
        onClaimed={() => {}}
        onAlreadyClaimed={() => {}}
      />,
    )
    expect(screen.getByLabelText('Setup code')).toBeInTheDocument()
    expect(screen.getByText(/docker logs memar/)).toBeInTheDocument()
  })

  it('reveals the code field after a 403 code_required response', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { detail: 'code_required' }))
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    expect(screen.queryByLabelText('Setup code')).toBeNull()
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    expect(await screen.findByLabelText('Setup code')).toBeInTheDocument()
  })

  it('shows a clear message for a wrong code (403 code_invalid)', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(403, { detail: 'code_invalid' }))
    render(
      <FirstRunSetup status={{ ...baseStatus, code_required: true }} onClaimed={() => {}} onAlreadyClaimed={() => {}} />,
    )
    fillValid('WRONG-CODE')
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    expect(
      await screen.findByText('That setup code is not right. Check it and try again.'),
    ).toBeInTheDocument()
  })

  it('switches to sign-in on 409 already_claimed', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(409, { detail: 'already_claimed' }))
    const onAlreadyClaimed = vi.fn()
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={onAlreadyClaimed} />)
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    await waitFor(() => expect(onAlreadyClaimed).toHaveBeenCalled())
    expect(localStorage.getItem('memar-access-token')).toBeNull()
  })

  it('maps 429 to a wait message', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(429, { detail: 'rate limited' }))
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    expect(await screen.findByText('Too many tries. Wait a minute.')).toBeInTheDocument()
  })

  it('shows the 422 detail message', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(422, { detail: 'Password is too common' }))
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    fillValid()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    expect(await screen.findByText('Password is too common')).toBeInTheDocument()
  })

  it('blocks a short password client-side without calling the API', () => {
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'owner' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    expect(screen.getByText('Password must be at least 10 characters.')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('FirstRunSetup licence key (paid plans)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    window.history.replaceState(null, '', '/')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const fill = () => {
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'owner' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-1' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'correct-horse-1' } })
    fireEvent.click(screen.getByRole('button', { name: /Add your license key/ }))
    fireEvent.change(screen.getByLabelText('License key (optional)'), { target: { value: '  AAAA\nBBBB  ' } })
  }

  it('activates the key with the new admin token and shows the plan', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(201, { access_token: 'acc-9', refresh_token: 'ref-9' }))
      .mockResolvedValueOnce(jsonResponse(200, { status: 'activated' }))
      .mockResolvedValueOnce(jsonResponse(200, { tier: 'farm', device_limit: 150 }))
    const onClaimed = vi.fn()
    render(<FirstRunSetup status={baseStatus} onClaimed={onClaimed} onAlreadyClaimed={() => {}} />)
    fill()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Farm plan active — up to 150 devices'))
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toContain('/api/license/activate')
    expect(init.headers.Authorization).toBe('Bearer acc-9')
    expect(JSON.parse(init.body)).toEqual({ license_key: 'AAAABBBB' })
    expect(onClaimed).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue to add devices' }))
    expect(onClaimed).toHaveBeenCalledWith('owner')
  })

  it('a rejected key does not block setup', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(201, { access_token: 'acc-9', refresh_token: 'ref-9' }))
      .mockResolvedValueOnce(jsonResponse(400, { detail: 'Invalid or expired license key' }))
    const onClaimed = vi.fn()
    render(<FirstRunSetup status={baseStatus} onClaimed={onClaimed} onAlreadyClaimed={() => {}} />)
    fill()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('not accepted'))
    expect(localStorage.length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Continue to add devices' }))
    expect(onClaimed).toHaveBeenCalledWith('owner')
  })

  it('rejected key: warning heading and the real button name, never blocking', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(201, { access_token: 'acc-9', refresh_token: 'ref-9' }))
      .mockResolvedValueOnce(jsonResponse(400, { detail: 'Invalid or expired license key' }))
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    fill()
    fireEvent.click(screen.getByRole('button', { name: 'Create admin account' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('License key not accepted'))
    expect(screen.getByRole('status')).toHaveTextContent('Free plan · Upgrade')
  })
})

describe('FirstRunSetup password visibility', () => {
  it('Show passwords reveals both password fields', () => {
    render(<FirstRunSetup status={baseStatus} onClaimed={() => {}} onAlreadyClaimed={() => {}} />)
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    fireEvent.click(screen.getByLabelText('Show passwords'))
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('type', 'text')
  })
})
