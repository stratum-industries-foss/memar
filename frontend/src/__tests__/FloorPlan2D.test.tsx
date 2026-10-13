import { render, act } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { FloorPlan2D, DevicePosition } from '../FloorPlan2D'

// jsdom loads no real images and reports zero layout for everything, so this
// test does not (and cannot) verify literal pixel-perfect rendering against a
// real photo -- that's a real-browser/manual check (see BUG-HIGH-FE-05.md).
// What IS testable, precisely, without faking anything: the actual defect was
// that device screen position was computed by two INDEPENDENT transforms in
// edit vs. view mode, with no relationship to where the image renders. This
// test stubs a fixed image natural size and a fixed container size (the two
// real inputs the shared `imageRect` transform depends on) and asserts the
// SAME device produces the SAME screen position in both modes -- the actual
// invariant the fix establishes.

const REAL_IMAGE = window.Image

function stubImageLoad(naturalWidth: number, naturalHeight: number) {
  class StubImage {
    naturalWidth = naturalWidth
    naturalHeight = naturalHeight
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    private _src = ''
    set src(v: string) {
      this._src = v
      // Real Image loading is async; queue a microtask like the browser would.
      queueMicrotask(() => this.onload?.())
    }
    get src() {
      return this._src
    }
  }
  // @ts-expect-error -- test stub, not a full Image implementation
  window.Image = StubImage
}

function stubContainerSize(container: HTMLElement, w: number, h: number) {
  const el = container.querySelector('.floorplan-container') as HTMLElement
  Object.defineProperty(el, 'clientWidth', { configurable: true, value: w })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: h })
  return el
}

function devicePosition(el: HTMLElement | null): { left: string; top: string } {
  if (!el) throw new Error('device element not found')
  return { left: el.style.left, top: el.style.top }
}

afterEach(() => {
  window.Image = REAL_IMAGE
})

describe('FloorPlan2D image registration (HIGH-FE-05)', () => {
  it('positions the same device identically in view and edit mode, given the same image and container size', async () => {
    stubImageLoad(800, 600)

    const devices: DevicePosition[] = [
      { device_id: 'p1', x: 200, y: 150, rotation: 0, status: 'idle' },
    ]

    const { container, rerender } = render(
      <FloorPlan2D devices={devices} imageUrl="test-floorplan.jpg" editMode={false} />
    )

    // Container is 100%-driven whenever an image is registered (both modes),
    // so the same stub applies before and after toggling editMode.
    stubContainerSize(container, 1000, 700)

    // Flush: image onload microtask, then the rAF-scheduled container measure.
    await act(async () => {
      await Promise.resolve()
      await new Promise(requestAnimationFrame)
    })

    const deviceEl = container.querySelector('[data-testid], .floorplan-device') as HTMLElement
    const viewPos = devicePosition(deviceEl)
    // Exact expected value for this scenario (hand-verified): image 800x600 in a
    // 1000x700 container under contain-fit -> scale = min(1000/800, 700/600) =
    // 1.1666..., offsetX = (1000 - 800*scale)/2 = 33.33, offsetY = 0. Device at
    // image-pixel (200, 150) -> screen (33.33 + 200*scale, 0 + 150*scale) =
    // (266.67, 175). Confirms the test is exercising the real imageRect math,
    // not coincidentally passing on some fallback/zero value.
    expect(parseFloat(viewPos.left)).toBeCloseTo(266.67, 1)
    expect(parseFloat(viewPos.top)).toBeCloseTo(175, 1)

    rerender(<FloorPlan2D devices={devices} imageUrl="test-floorplan.jpg" editMode={true} />)
    stubContainerSize(container, 1000, 700)
    await act(async () => {
      await Promise.resolve()
      await new Promise(requestAnimationFrame)
    })

    const deviceElEdit = container.querySelector('.floorplan-device') as HTMLElement
    const editPos = devicePosition(deviceElEdit)

    // The actual bug: these used to come from two independently-fitted
    // transforms and would differ. With the shared imageRect transform and
    // the same image + same container size, they must match exactly.
    expect(editPos.left).toBe(viewPos.left)
    expect(editPos.top).toBe(viewPos.top)
  })

  it('falls back to the pre-existing device-only transform when there is no image (unchanged behavior)', async () => {
    const devices: DevicePosition[] = [
      { device_id: 'p1', x: 50, y: 50, rotation: 0, status: 'idle' },
    ]
    const { container } = render(
      <FloorPlan2D devices={devices} imageUrl={null} editMode={false} />
    )
    await act(async () => {
      await new Promise(requestAnimationFrame)
    })
    const deviceEl = container.querySelector('.floorplan-device') as HTMLElement
    // No image => imageRect is null => falls back to viewBounds, exactly as
    // before this fix. Just confirms the no-image path still renders a
    // positioned device rather than throwing/blanking.
    expect(deviceEl).toBeTruthy()
    expect(deviceEl.style.left).not.toBe('')
  })

  it('sets an explicit non-zero inline size on the container in view mode with an image (prevents widget collapse)', async () => {
    // Regression guard: .floorplan-widget-section .floorplan-container is
    // `height: auto` in CSS with a comment saying the component supplies the
    // size via inline style in view mode, and every child is
    // position:absolute (zero auto-height contribution). If the component
    // stops setting an explicit inline height here whenever an image is
    // registered, the widget silently collapses to ~0px in view mode in the
    // real app -- jsdom won't reproduce the collapse itself (it doesn't
    // compute the CSS cascade), so this asserts the actual mechanism that
    // prevents it: the component's own inline style.
    stubImageLoad(800, 600)
    const devices: DevicePosition[] = [
      { device_id: 'p1', x: 100, y: 100, rotation: 0, status: 'idle' },
    ]
    const { container } = render(
      <FloorPlan2D devices={devices} imageUrl="test-floorplan.jpg" editMode={false} />
    )
    await act(async () => {
      await Promise.resolve()
      await new Promise(requestAnimationFrame)
    })
    const el = container.querySelector('.floorplan-container') as HTMLElement
    expect(el.style.height).not.toBe('')
    expect(parseFloat(el.style.height)).toBeGreaterThan(0)
    expect(el.style.width).not.toBe('')
    expect(parseFloat(el.style.width)).toBeGreaterThan(0)
  })
})
