# MEMAR Drawer Components Architecture

## Overview

This directory contains the modular drawer components extracted from the monolithic `App.tsx` (originally 7,355 lines). The new architecture uses:

- **React.lazy()** for code splitting (each drawer lazy-loads)
- **DrawerProvider context** for state management
- **Unified DrawerProps** type for component interface
- **Component registry** for dynamic rendering

## Architecture

### Key Files

- **App.tsx** (~270 lines) — Main app component with:
  - DrawerProvider wrapper
  - Drawer component registry
  - Tab bar for drawer selection
  - Message handler
  - State props distribution

- **index.ts** — Barrel export for all 18 drawers

### 18 Drawer Components

| Drawer | Lines | Status | Notes |
|--------|-------|--------|-------|
| OverviewDrawer | 250+ | ✅ Full | Machine state, metrics, filament, exclude objects |
| TemperatureDrawer | 100+ | ✅ Full | Nozzle/bed control, presets, history graph |
| JogDrawer | Stub | ⏳ Extract | Motion control (requires canWrite) |
| MacrosDrawer | Stub | ⏳ Extract | Macro execution with params |
| FilesDrawer | Stub | ⏳ Extract | File browser, upload, print counts |
| SettingsDrawer | Stub | ⏳ Extract | Printer settings, profile, maintenance |
| HistoryDrawer | Stub | ⏳ Extract | Job history, filtering, reprint |
| WebcamsDrawer | Stub | ⏳ Extract | Webcam feed display |
| DryrunDrawer | Stub | ⏳ Extract | Action dry-run, motion check, dispatch preflight |
| TimelapseDrawer | Stub | ⏳ Extract | Timelapse artifacts, media player |
| ConsoleDrawer | Stub | ⏳ Extract | G-code REPL (requires canWrite) |
| BedmeshDrawer | Stub | ⏳ Extract | Bed mesh visualization (requires canWrite) |
| QueueDrawer | ✅ Proxy | Wraps FleetTools.QueuePanel |
| MaintenanceDrawer | ✅ Proxy | Wraps FleetTools.MaintenancePanel |
| HealthDrawer | ✅ Proxy | Wraps FleetTools.HealthPanel |
| CncDrawer | ✅ Proxy | Wraps CNCMetricsPanel |
| CoolantDrawer | ✅ Proxy | Wraps CoolantMetricsPanel |
| AnalyticsDrawer | ✅ Full | Device analytics summary |

## Migration Guide

### Step 1: Extract UI from Original App.tsx

For each `⏳ Extract` drawer:

1. Open original App.tsx
2. Find the section (line ranges in table above)
3. Copy JSX + relevant state/handlers
4. Paste into drawer component
5. Update prop destructuring to use DrawerProps
6. Replace inline functions with prop references

Example:
```typescript
// Old App.tsx (inline)
{activeSection === 'jog' && canWrite && (
  <section className="drawer-section">
    {/* 50 lines of JSX */}
  </section>
)}

// New JogDrawer.tsx
export default function JogDrawer({ canWrite, ...props }: DrawerProps) {
  if (!canWrite) return null
  return (
    <section className="drawer-section">
      {/* Same JSX, no conditional */}
    </section>
  )
}
```

### Step 2: Update App.tsx State Distribution

Add missing state props to the `drawerProps` object in App.tsx:

```typescript
const drawerProps: DrawerProps = useMemo(() => ({
  // Existing
  printerId: detailsPrinterId || undefined,
  diagnostics,
  canWrite,
  
  // Add these for each drawer
  currentPrinter,
  tempPresets,
  customNozzle,
  setCustomNozzle,
  // ... etc
}), [/* deps */])
```

### Step 3: Integrate State Handlers

Move drawer-specific functions to App.tsx and pass via props:

```typescript
// State
const [jogDistance, setJogDistance] = useState('1')

// Handler
const runJogNow = useCallback((distance: number) => {
  // API call
}, [detailsPrinterId])

// Pass via props
const drawerProps = { ..., jogDistance, setJogDistance, runJogNow }
```

### Step 4: Test Each Drawer

After extracting each drawer:

```bash
npm run build   # Check for TS errors
npm run dev     # Manual test in browser
```

Verify:
- Lazy loading (inspect Network tab, chunks should split)
- Props propagation (no undefined errors)
- Functionality (buttons work, data flows)
- Styling (CSS classes exist in stylesheet)

## Type Safety

### DrawerProps Interface

```typescript
export type DrawerProps = {
  // Minimal required
  printerId?: string
  printer?: any
  currentPrinter?: any
  diagnostics?: any
  canWrite?: boolean
  onDone?: () => void
  
  // Optional for specific drawers
  [key: string]: any
}
```

**Note:** Stub drawers use loose typing (`...props: DrawerProps`) until fully extracted. Strongly type each drawer once extracted:

```typescript
type JogDrawerProps = DrawerProps & {
  jogDistance: string
  setJogDistance: (val: string) => void
  runJogNow: (distance: number) => Promise<void>
}

export default function JogDrawer({
  jogDistance,
  setJogDistance,
  runJogNow,
}: JogDrawerProps) { ... }
```

## Code Splitting Results

### Before (Monolithic)
- Single bundle: ~7,355-line App.tsx
- Load time: All code loaded upfront

### After (Modular)
- Main bundle: ~270 lines (App.tsx)
- Drawer chunks: ~50-250 lines each (lazy-loaded)
- Load time: Only active drawer loaded
- Estimated first-load savings: ~40% (drawers only load on click)

## Context Management

### DrawerProvider

Wraps the entire app, manages:
- `activeSection` — which drawer is visible
- `drawerMessage` — toast/alert at drawer top
- `setActiveSection()` — switch drawers
- `setDrawerMessage()` — show message

Usage in drawers:
```typescript
import { useDrawerContext } from '../App'

export default function MyDrawer() {
  const { setDrawerMessage } = useDrawerContext()
  
  const handleAction = async () => {
    try {
      await doSomething()
      setDrawerMessage({ text: 'Success!', severity: 'success' })
    } catch (e) {
      setDrawerMessage({ text: 'Error: ' + e.message, severity: 'error' })
    }
  }
}
```

## Checklist: Full Migration

- [ ] All 18 drawers extracted and building
- [ ] State handlers integrated into App.tsx
- [ ] Props passed correctly (no undefined props)
- [ ] Each drawer renders without errors
- [ ] All drawers are lazy-loaded (check Network tab)
- [ ] Tab clicks switch drawers smoothly
- [ ] Message handler works (try setDrawerMessage)
- [ ] Read-only check for jog/console/bedmesh passes
- [ ] No regression in existing functionality
- [ ] TypeScript strict mode passes
- [ ] Lint passes (eslint, prettier)

## Future Improvements

1. **Per-drawer hooks** — Extract drawer-specific logic into custom hooks
2. **State splitting** — Use Zustand/Recoil for fine-grained state management
3. **Code size audit** — Check bundle size vs. original
4. **Performance** — Add React.memo() to drawers if re-render spam detected
5. **Storybook** — Add drawer stories for isolated testing
6. **E2E tests** — Cypress tests for tab switching + drawer interactions
