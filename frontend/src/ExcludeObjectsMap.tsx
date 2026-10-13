/**
 * ExcludeObjectsMap — interactive SVG bed map of exclude_object regions.
 *
 * Klipper's `[exclude_object]` module reports one entry per object the slicer
 * declared via `EXCLUDE_OBJECT_DEFINE`. When the slicer emits POLYGON data each
 * entry carries a `polygon` (a closed ring of [x, y] bed coordinates, mm), which
 * lets us draw the actual plate layout instead of an anonymous list of buttons.
 *
 * Two coordinate details matter:
 *
 *  1. The viewBox is derived from the polygons' own bounding box, NOT from
 *     `capability.build_volume`. Build volume comes from `stepper_*.position_max`
 *     in printer.cfg (see backend/app/config_discovery.py) and is legitimately
 *     absent/0 on printers whose config we could not parse — keying the viewBox
 *     off it would collapse the map to nothing on exactly those printers.
 *
 *  2. Bed coordinates are y-up; SVG user space is y-down. The polygon layer is
 *     wrapped in `transform="scale(1, -1)"` so the plate renders in the same
 *     orientation the operator sees it. Labels are placed at manually negated
 *     y values OUTSIDE that group, since mirroring text renders it backwards.
 *
 * Exclusion is one-way: Klipper has no supported "un-exclude mid-print" path
 * through this API, so an excluded region is permanently disabled here and the
 * caller is expected to gate `onExclude` behind a confirmation dialog.
 */

import { useMemo, useState } from 'react'

export type ExcludeObject = {
  name: string
  polygon?: number[][]
  center?: number[]
}

/** A polygon we can actually draw: at least 3 finite vertices. */
type Ring = Array<[number, number]>

/**
 * Coerce Moonraker's loosely-typed polygon into finite [x, y] pairs.
 * Returns null when the ring has fewer than 3 usable vertices (a point or a
 * line segment has no interior to click, so it is not renderable as a region).
 */
function toRing(polygon: unknown): Ring | null {
  if (!Array.isArray(polygon)) return null
  const ring: Ring = []
  for (const pt of polygon) {
    if (!Array.isArray(pt) || pt.length < 2) continue
    const x = Number(pt[0])
    const y = Number(pt[1])
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    ring.push([x, y])
  }
  return ring.length >= 3 ? ring : null
}

/**
 * True when at least one object carries a drawable polygon. Callers use this to
 * decide between this map and the plain button-list fallback — slicers that omit
 * POLYGON from EXCLUDE_OBJECT_DEFINE still report object names, and those remain
 * excludable, just not visually.
 */
export function hasPolygonData(objects: ExcludeObject[] | null | undefined): boolean {
  if (!Array.isArray(objects)) return false
  return objects.some((obj) => toRing(obj?.polygon) !== null)
}

type Bounds = { minX: number; minY: number; maxX: number; maxY: number }

function ringsBounds(rings: Ring[]): Bounds {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const ring of rings) {
    for (const [x, y] of ring) {
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  }
  return { minX, minY, maxX, maxY }
}

export type ExcludeObjectsMapProps = {
  objects: ExcludeObject[]
  excluded: string[]
  currentObject?: string | null
  /** False for viewer-role users: regions render but are not actionable. */
  canWrite: boolean
  /** Invoked with the object name on click/Enter/Space. Caller owns confirmation. */
  onExclude: (name: string) => void
}

export function ExcludeObjectsMap({
  objects,
  excluded,
  currentObject,
  canWrite,
  onExclude,
}: ExcludeObjectsMapProps) {
  const [hovered, setHovered] = useState<string | null>(null)

  const model = useMemo(() => {
    const drawable = objects
      .map((obj) => ({ obj, ring: toRing(obj?.polygon) }))
      .filter((entry): entry is { obj: ExcludeObject; ring: Ring } => entry.ring !== null)

    if (drawable.length === 0) return null

    const raw = ringsBounds(drawable.map((d) => d.ring))
    // A single tiny object (or several stacked at one spot) can yield a
    // near-zero span; a zero-width/height viewBox is invalid SVG and renders
    // nothing, so floor the span before padding.
    const spanX = Math.max(raw.maxX - raw.minX, 1)
    const spanY = Math.max(raw.maxY - raw.minY, 1)
    const pad = Math.max(spanX, spanY) * 0.06

    const vbW = spanX + pad * 2
    const vbH = spanY + pad * 2
    const vbX = raw.minX - pad
    // Under scale(1, -1) a bed point (x, y) lands at (x, -y), so the drawn
    // content spans y in [-maxY, -minY]: the viewBox origin is the NEGATED top.
    const vbY = -(raw.minY + spanY) - pad

    const unit = Math.max(spanX, spanY)
    // Hatch and label sizes live in user units, so they must scale with the
    // plate or they vanish on a 350mm bed and swamp a 20mm one.
    const hatch = Math.max(unit / 40, 0.5)
    const labelSize = Math.max(unit / 32, 0.5)

    const regions = drawable.map(({ obj, ring }) => {
      const b = ringsBounds([ring])
      return {
        name: obj.name,
        points: ring.map(([x, y]) => `${x},${y}`).join(' '),
        // Label anchor: polygon centroid-ish (bbox center) with y negated to
        // undo the flip, since labels render outside the mirrored group.
        labelX: (b.minX + b.maxX) / 2,
        labelY: -((b.minY + b.maxY) / 2),
        width: b.maxX - b.minX,
      }
    })

    return { viewBox: `${vbX} ${vbY} ${vbW} ${vbH}`, vbW, vbH, hatch, labelSize, regions }
  }, [objects])

  if (!model) return null

  const excludedSet = new Set(excluded)

  return (
    <div className="exclude-map-wrap">
      <svg
        className="exclude-map"
        viewBox={model.viewBox}
        preserveAspectRatio="xMidYMid meet"
        style={{ aspectRatio: `${model.vbW} / ${model.vbH}` }}
        role="group"
        aria-label="Print bed object map"
      >
        <defs>
          <pattern
            id="memar-exclude-hatch"
            patternUnits="userSpaceOnUse"
            width={model.hatch}
            height={model.hatch}
            patternTransform="rotate(45)"
          >
            {/* Fill/stroke colours come from the stylesheet, not `fill=`/`stroke=`
                attributes: var() inside SVG presentation attributes is unevenly
                supported. Tinted tile + diagonal rule = red hatch. */}
            <rect className="exclude-hatch-bg" width={model.hatch} height={model.hatch} />
            <line
              className="exclude-hatch-line"
              x1={0}
              y1={0}
              x2={0}
              y2={model.hatch}
              strokeWidth={model.hatch / 3}
            />
          </pattern>
        </defs>

        {/* Mirrored layer: geometry only. Text must stay out of here. */}
        <g transform="scale(1, -1)" data-testid="exclude-map-flip">
          {model.regions.map((region) => {
            const isExcluded = excludedSet.has(region.name)
            const isCurrent = currentObject === region.name
            const actionable = canWrite && !isExcluded
            const cls = [
              'exclude-polygon',
              isExcluded ? 'excluded' : '',
              isCurrent ? 'current' : '',
              actionable ? '' : 'readonly',
              hovered === region.name ? 'hovered' : '',
            ]
              .filter(Boolean)
              .join(' ')

            return (
              <polygon
                key={region.name}
                className={cls}
                points={region.points}
                vectorEffect="non-scaling-stroke"
                data-name={region.name}
                role="button"
                tabIndex={actionable ? 0 : -1}
                aria-disabled={!actionable}
                aria-label={
                  isExcluded
                    ? `${region.name} — already excluded`
                    : `Exclude ${region.name} from print`
                }
                onMouseEnter={() => setHovered(region.name)}
                onMouseLeave={() => setHovered((h) => (h === region.name ? null : h))}
                onFocus={() => setHovered(region.name)}
                onBlur={() => setHovered((h) => (h === region.name ? null : h))}
                onClick={() => actionable && onExclude(region.name)}
                onKeyDown={(e) => {
                  if (!actionable) return
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onExclude(region.name)
                  }
                }}
              >
                <title>
                  {isExcluded ? `${region.name} (excluded)` : region.name}
                  {isCurrent ? ' — printing now' : ''}
                </title>
              </polygon>
            )
          })}
        </g>

        {/* Unmirrored label layer. Skipped when the region is too narrow to
            hold the text — the <title> tooltip still identifies those. */}
        <g className="exclude-map-labels" aria-hidden="true">
          {model.regions.map((region) => {
            const fits = region.width > region.name.length * model.labelSize * 0.55
            if (!fits) return null
            return (
              <text
                key={region.name}
                className={`exclude-map-label${excludedSet.has(region.name) ? ' excluded' : ''}`}
                x={region.labelX}
                y={region.labelY}
                fontSize={model.labelSize}
                textAnchor="middle"
                dominantBaseline="middle"
              >
                {region.name}
              </text>
            )
          })}
        </g>
      </svg>

      <div className="exclude-map-status subtle small" aria-live="polite">
        {hovered
          ? excludedSet.has(hovered)
            ? `${hovered} — already excluded`
            : canWrite
              ? `Click to exclude ${hovered}`
              : `${hovered} — requires operator or admin role`
          : 'Hover or focus a region to identify it.'}
      </div>

      <div className="exclude-map-legend small subtle">
        <span><i className="exclude-swatch active" /> active</span>
        <span><i className="exclude-swatch printing" /> printing now</span>
        <span><i className="exclude-swatch excluded" /> excluded</span>
      </div>
    </div>
  )
}
