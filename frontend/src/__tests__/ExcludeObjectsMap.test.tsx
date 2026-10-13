import { render, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ExcludeObjectsMap, hasPolygonData, type ExcludeObject } from '../ExcludeObjectsMap'

/**
 * Canned payload shaped like Moonraker's `exclude_object.objects`: two 10mm
 * squares on a 200mm bed, one near the origin and one offset in +x/+y.
 */
const OBJECTS: ExcludeObject[] = [
  {
    name: 'cube_a',
    center: [15, 15],
    polygon: [[10, 10], [20, 10], [20, 20], [10, 20]],
  },
  {
    name: 'cube_b',
    center: [55, 45],
    polygon: [[50, 40], [60, 40], [60, 50], [50, 50]],
  },
]

function renderMap(overrides: Partial<React.ComponentProps<typeof ExcludeObjectsMap>> = {}) {
  const onExclude = vi.fn()
  const utils = render(
    <ExcludeObjectsMap
      objects={OBJECTS}
      excluded={[]}
      currentObject={null}
      canWrite
      onExclude={onExclude}
      {...overrides}
    />,
  )
  return { ...utils, onExclude }
}

const poly = (c: HTMLElement, name: string) =>
  c.querySelector(`polygon[data-name="${name}"]`) as SVGPolygonElement

describe('hasPolygonData', () => {
  it('is true when at least one object carries a drawable ring', () => {
    expect(hasPolygonData(OBJECTS)).toBe(true)
  })

  it('is false when the slicer omitted POLYGON — caller falls back to the button list', () => {
    expect(hasPolygonData([{ name: 'a' }, { name: 'b' }])).toBe(false)
  })

  it('is false for rings with fewer than 3 vertices (no clickable interior)', () => {
    expect(hasPolygonData([{ name: 'a', polygon: [[1, 1], [2, 2]] }])).toBe(false)
  })

  it('is false for malformed input rather than throwing', () => {
    expect(hasPolygonData(null)).toBe(false)
    expect(hasPolygonData(undefined)).toBe(false)
    expect(hasPolygonData([{ name: 'a', polygon: 'nope' as unknown as number[][] }])).toBe(false)
  })
})

describe('ExcludeObjectsMap geometry', () => {
  it('renders one polygon per object with the raw bed coordinates', () => {
    const { container } = renderMap()
    const polys = container.querySelectorAll('polygon')
    expect(polys).toHaveLength(2)
    expect(poly(container, 'cube_a').getAttribute('points')).toBe('10,10 20,10 20,20 10,20')
    expect(poly(container, 'cube_b').getAttribute('points')).toBe('50,40 60,40 60,50 50,50')
  })

  it('derives the viewBox from the polygon bounding box, not a build volume', () => {
    const { container } = renderMap()
    const vb = container.querySelector('svg')!.getAttribute('viewBox')!
    const [x, y, w, h] = vb.split(' ').map(Number)

    // Union bbox is x 10..60, y 10..50 -> spans 50 x 40, pad = 6% of 50 = 3.
    expect(w).toBeCloseTo(56, 5) // 50 + 2*3
    expect(h).toBeCloseTo(46, 5) // 40 + 2*3
    expect(x).toBeCloseTo(7, 5) // minX 10 - 3
    // y is negated because the geometry layer is mirrored: -(maxY) - pad.
    expect(y).toBeCloseTo(-53, 5) // -(10 + 40) - 3
    expect([x, y, w, h].every(Number.isFinite)).toBe(true)
  })

  it('mirrors the geometry layer so a y-up bed renders y-up in y-down SVG space', () => {
    const { getByTestId } = renderMap()
    expect(getByTestId('exclude-map-flip').getAttribute('transform')).toBe('scale(1, -1)')
  })

  it('keeps labels outside the mirrored layer so text is not rendered backwards', () => {
    const { container, getByTestId } = renderMap()
    const flip = getByTestId('exclude-map-flip')
    const labels = container.querySelectorAll('text.exclude-map-label')
    expect(labels.length).toBeGreaterThan(0)
    labels.forEach((label) => expect(flip.contains(label)).toBe(false))
  })

  it('renders a single object without collapsing to a degenerate viewBox', () => {
    const { container } = renderMap({ objects: [OBJECTS[0]] })
    expect(container.querySelectorAll('polygon')).toHaveLength(1)
    const [, , w, h] = container.querySelector('svg')!.getAttribute('viewBox')!.split(' ').map(Number)
    expect(w).toBeGreaterThan(0)
    expect(h).toBeGreaterThan(0)
  })

  it('floors the span for a zero-area ring so the viewBox stays valid SVG', () => {
    const { container } = renderMap({
      objects: [{ name: 'dot', polygon: [[5, 5], [5, 5], [5, 5]] }],
    })
    const [x, y, w, h] = container.querySelector('svg')!.getAttribute('viewBox')!.split(' ').map(Number)
    expect([x, y].every(Number.isFinite)).toBe(true)
    expect(w).toBeGreaterThan(0)
    expect(h).toBeGreaterThan(0)
  })

  it('skips objects with no polygon but still draws the ones that have it', () => {
    const { container } = renderMap({ objects: [OBJECTS[0], { name: 'nameless' }] })
    expect(container.querySelectorAll('polygon')).toHaveLength(1)
    expect(poly(container, 'cube_a')).toBeTruthy()
  })

  it('renders nothing when no object has usable geometry', () => {
    const { container } = renderMap({ objects: [{ name: 'a' }] })
    expect(container.querySelector('svg')).toBeNull()
  })

  it('layers overlapping polygons rather than dropping either', () => {
    const overlapping: ExcludeObject[] = [
      { name: 'lower', polygon: [[0, 0], [30, 0], [30, 30], [0, 30]] },
      { name: 'upper', polygon: [[10, 10], [40, 10], [40, 40], [10, 40]] },
    ]
    const { container } = renderMap({ objects: overlapping })
    expect(container.querySelectorAll('polygon')).toHaveLength(2)
  })
})

describe('ExcludeObjectsMap interaction', () => {
  it('calls onExclude with the object name on click', () => {
    const { container, onExclude } = renderMap()
    fireEvent.click(poly(container, 'cube_b'))
    expect(onExclude).toHaveBeenCalledExactlyOnceWith('cube_b')
  })

  it('is keyboard operable via Enter and Space', () => {
    const { container, onExclude } = renderMap()
    fireEvent.keyDown(poly(container, 'cube_a'), { key: 'Enter' })
    fireEvent.keyDown(poly(container, 'cube_a'), { key: ' ' })
    expect(onExclude).toHaveBeenCalledTimes(2)
    expect(onExclude).toHaveBeenCalledWith('cube_a')
  })

  it('marks excluded regions visually distinct and refuses to re-fire them', () => {
    const { container, onExclude } = renderMap({ excluded: ['cube_a'] })
    const excludedPoly = poly(container, 'cube_a')

    expect(excludedPoly.getAttribute('class')).toContain('excluded')
    expect(excludedPoly.getAttribute('aria-disabled')).toBe('true')
    expect(excludedPoly.getAttribute('tabindex')).toBe('-1')
    // Exclusion is irreversible in Klipper — a second click must be inert.
    fireEvent.click(excludedPoly)
    fireEvent.keyDown(excludedPoly, { key: 'Enter' })
    expect(onExclude).not.toHaveBeenCalled()

    // The un-excluded sibling stays actionable.
    expect(poly(container, 'cube_b').getAttribute('class')).not.toContain('excluded')
  })

  it('renders read-only for viewers without write scope', () => {
    const { container, onExclude } = renderMap({ canWrite: false })
    const target = poly(container, 'cube_a')
    expect(target.getAttribute('class')).toContain('readonly')
    expect(target.getAttribute('aria-disabled')).toBe('true')
    fireEvent.click(target)
    expect(onExclude).not.toHaveBeenCalled()
  })

  it('flags the object currently being printed', () => {
    const { container } = renderMap({ currentObject: 'cube_b' })
    expect(poly(container, 'cube_b').getAttribute('class')).toContain('current')
    expect(poly(container, 'cube_a').getAttribute('class')).not.toContain('current')
  })

  it('identifies the region under the pointer in the status line', () => {
    const { container, getByText } = renderMap()
    fireEvent.mouseEnter(poly(container, 'cube_a'))
    expect(getByText('Click to exclude cube_a')).toBeInTheDocument()
    fireEvent.mouseLeave(poly(container, 'cube_a'))
    expect(getByText('Hover or focus a region to identify it.')).toBeInTheDocument()
  })
})
