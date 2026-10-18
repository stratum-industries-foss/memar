import { render, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { CoolantTrendChart } from '../CoolantTrendChart'

function makeData(n: number, valueOf: (i: number) => number = () => 50) {
  return Array.from({ length: n }, (_, i) => ({
    timestamp: new Date(2026, 0, 1, 0, i).toISOString(),
    value: valueOf(i),
  }))
}

describe('CoolantTrendChart stale hover', () => {
  it('does not crash when data shrinks below the hovered index', () => {
    const { container, rerender } = render(<CoolantTrendChart data={makeData(10)} />)

    // CSS-module class names are hashed (styles['trend-interaction-layer']), so locate the
    // interaction layer by element rather than by class name.
    const layer = container.querySelector('svg') as SVGSVGElement | null
    expect(layer).toBeTruthy()

    // jsdom returns a zero-size rect by default; stub a real one so the mousemove ->
    // hoveredIndex math resolves to the last point (index 9).
    layer.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 600, height: 300, right: 600, bottom: 300, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
    fireEvent.mouseMove(layer, { clientX: 575, clientY: 10 })

    // Background refresh delivers a SHORTER array while hoveredIndex (9) is still set.
    expect(() => rerender(<CoolantTrendChart data={makeData(1)} />)).not.toThrow()
  })

  it('shows the new last point after a shorter refresh, not a stale point', () => {
    // Distinct values per point, so a stale index is visible in the tooltip.
    // Hovering index 9 of 10, then the data shrinks to 4 points (values 100..103).
    const { container, rerender, getByText, queryByText } = render(
      <CoolantTrendChart data={makeData(10, (i) => 200 + i)} />
    )
    // Two SVGs render: the chart, then the interaction overlay that owns onMouseMove. Use the last.
    const svgs = container.querySelectorAll('svg')
    const layer = svgs[svgs.length - 1] as SVGSVGElement
    layer.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 600, height: 300, right: 600, bottom: 300, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
    fireEvent.mouseMove(layer, { clientX: 575, clientY: 10 })

    rerender(<CoolantTrendChart data={makeData(4, (i) => 100 + i)} />)

    // The tooltip must show the new last point (103.0). A stale index would show a value
    // from the old array, or nothing; this assertion fails in both cases.
    expect(queryByText(/209\.0/)).toBeNull()
    expect(getByText(/103\.0/)).toBeTruthy()
  })
})
