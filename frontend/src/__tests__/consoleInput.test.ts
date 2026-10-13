import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  handleConsoleKey,
  completionCandidates,
  appendConsoleHistory,
  loadConsoleHistory,
  saveConsoleHistory,
  consoleHistoryKey,
  CONSOLE_HISTORY_LIMIT,
  NO_COMPLETION_CYCLE,
  type ConsoleKeyState,
} from '../consoleInput'

/** Build a fake keydown with a spy-able preventDefault. */
function key(k: string) {
  return { key: k, preventDefault: vi.fn() }
}

function state(over: Partial<ConsoleKeyState> = {}): ConsoleKeyState {
  return { input: '', history: [], historyIndex: 0, cycle: NO_COMPLETION_CYCLE, ...over }
}

describe('completionCandidates', () => {
  it('matches the static gcode vocabulary by prefix, case-insensitively', () => {
    expect(completionCandidates('g2')).toContain('G28')
    expect(completionCandidates('G2')).toContain('G29')
    expect(completionCandidates('save')).toEqual(['SAVE_CONFIG'])
  })

  it('merges printer macros ahead of the static list and dedupes them', () => {
    const found = completionCandidates('start', ['START_PRINT'])
    expect(found).toEqual(['START_PRINT'])
    // SAVE_CONFIG exists in both the macro list and the static list — one entry.
    expect(completionCandidates('save_c', ['SAVE_CONFIG'])).toEqual(['SAVE_CONFIG'])
  })

  it('returns nothing for an empty prefix rather than the whole vocabulary', () => {
    expect(completionCandidates('')).toEqual([])
    expect(completionCandidates('   ')).toEqual([])
  })

  it('returns nothing once the user is typing arguments', () => {
    // "M104 S200" is a command plus a parameter, not a prefix to complete.
    expect(completionCandidates('M104 S200')).toEqual([])
  })

  it('returns nothing for a non-prefix typo', () => {
    // Guards against anyone "fixing" this with fuzzy matching: SAVER is not a
    // prefix of SAVE_CONFIG and must not silently complete to it.
    expect(completionCandidates('SAVER')).toEqual([])
  })
})

describe('handleConsoleKey — TAB completion', () => {
  it('completes a partial command and calls preventDefault so focus stays put', () => {
    const e = key('Tab')
    const next = handleConsoleKey(e, state({ input: 'G2' }))
    expect(e.preventDefault).toHaveBeenCalled()
    expect(next?.input).toBe('G28')
  })

  it('completes an exact-but-lowercase prefix to the canonical uppercase form', () => {
    const next = handleConsoleKey(key('Tab'), state({ input: 'save_config' }))
    expect(next?.input).toBe('SAVE_CONFIG')
  })

  it('cycles through multiple matches on repeated TAB', () => {
    const candidates = completionCandidates('G2')
    expect(candidates.length).toBeGreaterThan(1)

    let s = state({ input: 'G2' })
    const seen: string[] = []
    for (let i = 0; i < candidates.length; i++) {
      const next = handleConsoleKey(key('Tab'), s)!
      seen.push(next.input)
      s = { ...s, input: next.input, cycle: next.cycle }
    }
    expect(seen).toEqual(candidates)

    // Wraps back to the first match.
    const wrapped = handleConsoleKey(key('Tab'), s)!
    expect(wrapped.input).toBe(candidates[0])
  })

  it('restarts the cycle from the new prefix once the input changes', () => {
    // TAB twice on "G2"...
    let s = state({ input: 'G2' })
    const first = handleConsoleKey(key('Tab'), s)!
    s = { ...s, input: first.input, cycle: first.cycle }
    const second = handleConsoleKey(key('Tab'), s)!
    expect(second.cycle.index).toBe(1)

    // ...then the user types, which the input's onChange clears the cycle for.
    // The next TAB must start at the first match of the NEW prefix, not resume
    // at the stale index.
    const typed = handleConsoleKey(key('Tab'), state({ input: 'M10', cycle: NO_COMPLETION_CYCLE }))!
    expect(typed.input).toBe(completionCandidates('M10')[0])
    expect(typed.cycle.index).toBe(0)
  })

  it('leaves the input untouched when nothing matches, but still preventDefaults', () => {
    const e = key('Tab')
    const next = handleConsoleKey(e, state({ input: 'ZZZQQ' }))
    expect(e.preventDefault).toHaveBeenCalled()
    expect(next?.input).toBe('ZZZQQ')
    expect(next?.cycle).toEqual(NO_COMPLETION_CYCLE)
  })
})

describe('handleConsoleKey — history browsing', () => {
  const history = ['G28', 'M104 S200']

  it('walks backwards from the newest entry on ArrowUp', () => {
    const e = key('ArrowUp')
    // historyIndex starts at history.length (the "not browsing" sentinel).
    const first = handleConsoleKey(e, state({ history, historyIndex: 2 }))!
    expect(e.preventDefault).toHaveBeenCalled()
    expect(first.input).toBe('M104 S200')

    const second = handleConsoleKey(key('ArrowUp'), state({ history, historyIndex: first.historyIndex }))!
    expect(second.input).toBe('G28')
  })

  it('stops at the oldest entry instead of running off the start', () => {
    const next = handleConsoleKey(key('ArrowUp'), state({ history, historyIndex: 0 }))!
    expect(next.input).toBe('G28')
    expect(next.historyIndex).toBe(0)
  })

  it('clears the input when arrowing down past the newest entry', () => {
    const next = handleConsoleKey(key('ArrowDown'), state({ history, historyIndex: 1, input: 'M104 S200' }))!
    expect(next.input).toBe('')
    expect(next.historyIndex).toBe(history.length)
  })

  it('preventDefaults the arrows so the caret does not jump', () => {
    const up = key('ArrowUp')
    handleConsoleKey(up, state({ history, historyIndex: 2 }))
    expect(up.preventDefault).toHaveBeenCalled()
    const down = key('ArrowDown')
    handleConsoleKey(down, state({ history, historyIndex: 0 }))
    expect(down.preventDefault).toHaveBeenCalled()
  })

  it('cancels an in-progress TAB cycle', () => {
    const next = handleConsoleKey(key('ArrowUp'), state({ history, historyIndex: 2, cycle: { prefix: 'G2', index: 1 } }))!
    expect(next.cycle).toEqual(NO_COMPLETION_CYCLE)
  })
})

describe('handleConsoleKey — keys it does not own', () => {
  it('returns null for Enter so the caller still submits', () => {
    expect(handleConsoleKey(key('Enter'), state({ input: 'G28' }))).toBeNull()
  })

  it('returns null for ordinary typing', () => {
    expect(handleConsoleKey(key('a'), state())).toBeNull()
  })
})

describe('appendConsoleHistory', () => {
  it('appends in chronological order', () => {
    expect(appendConsoleHistory(['G28'], 'M114')).toEqual(['G28', 'M114'])
  })

  it('dedupes only consecutive identical entries', () => {
    expect(appendConsoleHistory(['G28'], 'G28')).toEqual(['G28'])
    // A B A is a real sequence and must survive.
    expect(appendConsoleHistory(['G28', 'M114'], 'G28')).toEqual(['G28', 'M114', 'G28'])
  })

  it('ignores blank commands and trims', () => {
    expect(appendConsoleHistory(['G28'], '   ')).toEqual(['G28'])
    expect(appendConsoleHistory([], '  M114  ')).toEqual(['M114'])
  })

  it('caps the history so localStorage cannot grow without bound', () => {
    let hist: string[] = []
    for (let i = 0; i < CONSOLE_HISTORY_LIMIT + 25; i++) hist = appendConsoleHistory(hist, `G${i}`)
    expect(hist).toHaveLength(CONSOLE_HISTORY_LIMIT)
    // The oldest entries are the ones dropped.
    expect(hist[hist.length - 1]).toBe(`G${CONSOLE_HISTORY_LIMIT + 24}`)
  })
})

describe('history persistence', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips through localStorage under a per-printer key', () => {
    saveConsoleHistory('printer-a', ['G28', 'M114'])
    expect(localStorage.getItem(consoleHistoryKey('printer-a'))).toBeTruthy()
    expect(loadConsoleHistory('printer-a')).toEqual(['G28', 'M114'])
  })

  it('keeps printers isolated from each other', () => {
    saveConsoleHistory('printer-a', ['G28'])
    saveConsoleHistory('printer-b', ['M114'])
    expect(loadConsoleHistory('printer-a')).toEqual(['G28'])
    expect(loadConsoleHistory('printer-b')).toEqual(['M114'])
  })

  it('returns empty for an unknown printer', () => {
    expect(loadConsoleHistory('nope')).toEqual([])
    expect(loadConsoleHistory('')).toEqual([])
  })

  it('survives corrupt stored data rather than throwing', () => {
    localStorage.setItem(consoleHistoryKey('printer-a'), 'not json{')
    expect(loadConsoleHistory('printer-a')).toEqual([])
    // Wrong shape, and non-string members inside a valid array.
    localStorage.setItem(consoleHistoryKey('printer-b'), '{"a":1}')
    expect(loadConsoleHistory('printer-b')).toEqual([])
    localStorage.setItem(consoleHistoryKey('printer-c'), '["G28",5,null]')
    expect(loadConsoleHistory('printer-c')).toEqual(['G28'])
  })
})
