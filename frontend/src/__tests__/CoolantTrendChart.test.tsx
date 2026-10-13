import { render, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { CoolantTrendChart } from '../CoolantTrendChart'

function makeData(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    timestamp: new Date(2026, 0, 1, 0, i).toISOString(),
    value: 50,
  }))
}

describe('CoolantTrendChart stale hover', () => {
  it('does not crash when data shrinks below the hovered index', () => {
    const { container, rerender } = render(<CoolantTrendChart data={makeData(10)} />)

    const layer = container.querySelector('.trend-interaction-layer') as SVGSVGElement
    expect(layer).toBeTruthy()

    // jsdom returns a zero-size rect by default; stub a real one so the mousemove ->
    // hoveredIndex math resolves to the last point (index 9).
    layer.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 600, height: 300, right: 600, bottom: 300, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
    fireEvent.mouseMove(layer, { clientX: 575, clientY: 10 })

    // Background refresh delivers a SHORTER array while hoveredIndex (9) is still set.
    expect(() => rerender(<CoolantTrendChart data={makeData(1)} />)).not.toThrow()
  })
})
