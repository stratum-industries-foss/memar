import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// FloorPlanEditor imports apiFetch (used only for 3D generation, not on this path).
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    apiFetch: vi.fn(async () => ({
      ok: false, status: 404, statusText: 'NF', json: async () => ({}),
    })),
  }
})

import { FloorPlanEditor } from '../FloorPlanEditor'

describe('FloorPlanEditor "Done Editing"', () => {
  it('persists the layout (does not silently discard) when Done Editing is clicked', async () => {
    const onLayoutUpdate = vi.fn().mockResolvedValue(undefined)
    render(
      <FloorPlanEditor
        devices={[{ device_id: 'p1', x: 10, y: 10, rotation: 0 }]}
        imageUrl={null}
        onLayoutUpdate={onLayoutUpdate}
        canEdit
      />
    )

    fireEvent.click(screen.getByTitle('Enter edit mode to reposition devices'))
    fireEvent.click(screen.getByText(/Done Editing/))

    // The fix persists via onLayoutUpdate. The bug never calls it (Done just exits).
    await waitFor(() => expect(onLayoutUpdate).toHaveBeenCalledTimes(1))
  })
})
