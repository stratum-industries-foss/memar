import React, { useState, useCallback } from 'react';
import styles from './ZBabystep.module.css';

interface ZBabystepProps {
  printerId: string;
  printerName?: string;
  currentOffset: number;
  sessionOffset: number;
  minOffset?: number;
  maxOffset?: number;
  stepSizes?: number[];
  isLoading?: boolean;
  isPrinting?: boolean;
  onOffsetChange?: (delta: number, newTotal: number) => Promise<void>;
  onReset?: () => Promise<void>;
  theme?: 'light' | 'dark';
}

interface ZBabystepState {
  currentOffset: number;
  sessionOffset: number;
  selectedStepSize: number;
  isAdjusting: boolean;
  lastAdjustmentTime: number;
  adjustmentQueue: Array<{ delta: number; timestamp: number }>;
  errorMessage: string | null;
}

const ZBabystep: React.FC<ZBabystepProps> = ({
  printerId,
  printerName = 'Printer',
  currentOffset,
  sessionOffset,
  minOffset = -5.0,
  maxOffset = 5.0,
  stepSizes = [0.01, 0.05, 0.1, 0.5],
  isLoading = false,
  isPrinting = true,
  onOffsetChange,
  onReset,
  theme = 'dark',
}) => {
  const [state, setState] = useState<ZBabystepState>({
    currentOffset,
    sessionOffset,
    selectedStepSize: stepSizes[1] || 0.05,
    isAdjusting: false,
    lastAdjustmentTime: 0,
    adjustmentQueue: [],
    errorMessage: null,
  });

  const [manualInput, setManualInput] = useState('');

  const getWarning = useCallback((): string | null => {
    if (state.currentOffset < -1.0) {
      return 'Nozzle too close to bed (offset < -1.0mm)';
    }
    if (state.currentOffset > 0.5) {
      return 'Nozzle too far from bed (offset > 0.5mm)';
    }
    return null;
  }, [state.currentOffset]);

  const validateOffset = useCallback((val: number): boolean => {
    return val >= minOffset && val <= maxOffset;
  }, [minOffset, maxOffset]);

  const debounceAdjustment = useCallback((delta: number) => {
    const now = Date.now();
    const timeSinceLastAdjustment = now - state.lastAdjustmentTime;

    // Rapid-fire protection: minimum 100ms between adjustments
    if (timeSinceLastAdjustment < 100) {
      return;
    }

    const newOffset = state.currentOffset + delta;

    if (!validateOffset(newOffset)) {
      setState(prev => ({
        ...prev,
        errorMessage: `Offset must be between ${minOffset} and ${maxOffset}mm`,
      }));
      return;
    }

    setState(prev => ({
      ...prev,
      currentOffset: newOffset,
      sessionOffset: prev.sessionOffset + delta,
      isAdjusting: true,
      lastAdjustmentTime: now,
      errorMessage: null,
    }));

    onOffsetChange?.(delta, newOffset).catch(err => {
      setState(prev => ({
        ...prev,
        currentOffset: currentOffset,
        sessionOffset: sessionOffset,
        errorMessage: (err as Error).message,
      }));
    }).finally(() => {
      setState(prev => ({ ...prev, isAdjusting: false }));
    });
  }, [state.currentOffset, state.lastAdjustmentTime, currentOffset, sessionOffset, validateOffset, minOffset, maxOffset, onOffsetChange]);

  const adjustZ = useCallback((delta: number) => {
    if (!isPrinting) return;
    debounceAdjustment(delta);
  }, [isPrinting, debounceAdjustment]);

  const handleManualAdjust = useCallback(async () => {
    if (!manualInput) return;

    const val = parseFloat(manualInput);
    if (isNaN(val)) {
      setState(prev => ({
        ...prev,
        errorMessage: 'Invalid input: enter a number',
      }));
      return;
    }

    const newOffset = state.currentOffset + val;

    if (!validateOffset(newOffset)) {
      setState(prev => ({
        ...prev,
        errorMessage: `Offset must be between ${minOffset} and ${maxOffset}mm`,
      }));
      return;
    }

    setState(prev => ({
      ...prev,
      currentOffset: newOffset,
      sessionOffset: prev.sessionOffset + val,
      isAdjusting: true,
      errorMessage: null,
    }));

    try {
      await onOffsetChange?.(val, newOffset);
      setManualInput('');
    } catch (err) {
      setState(prev => ({
        ...prev,
        currentOffset: currentOffset,
        sessionOffset: sessionOffset,
        errorMessage: (err as Error).message,
      }));
    } finally {
      setState(prev => ({ ...prev, isAdjusting: false }));
    }
  }, [manualInput, state.currentOffset, state.sessionOffset, currentOffset, sessionOffset, validateOffset, minOffset, maxOffset, onOffsetChange]);

  const handleReset = useCallback(async () => {
    setState(prev => ({
      ...prev,
      sessionOffset: 0,
      isAdjusting: true,
      errorMessage: null,
    }));

    try {
      await onReset?.();
    } catch (err) {
      setState(prev => ({
        ...prev,
        sessionOffset: sessionOffset,
        errorMessage: (err as Error).message,
      }));
    } finally {
      setState(prev => ({ ...prev, isAdjusting: false }));
    }
  }, [sessionOffset, onReset]);

  const warningMessage = getWarning();

  if (isLoading) {
    return (
      <div className={styles.babystepContainer}>
        <div style={{ padding: '20px', textAlign: 'center', color: '#999' }}>
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className={styles.babystepContainer}>
      {/* Offset Display */}
      <div className={styles.offsetDisplay}>
        <div className={styles.offsetRow}>
          <span className={styles.label}>Total Z-Offset</span>
          <span className={styles.value}>{state.currentOffset.toFixed(3)} mm</span>
        </div>
        <div className={styles.offsetRow}>
          <span className={styles.label}>Session Delta</span>
          <span
            className={`${styles.value} ${
              state.sessionOffset > 0
                ? styles.positive
                : state.sessionOffset < 0
                ? styles.negative
                : ''
            }`}
          >
            {state.sessionOffset > 0 ? '+' : ''}{state.sessionOffset.toFixed(3)} mm
          </span>
        </div>
      </div>

      {/* Step Size Grid */}
      <div className={styles.stepSizeGrid}>
        {stepSizes.map(size => (
          <button
            key={size}
            className={`${styles.stepBtn} ${
              state.selectedStepSize === size ? styles.active : ''
            }`}
            onClick={() => setState(prev => ({ ...prev, selectedStepSize: size }))}
            disabled={!isPrinting || state.isAdjusting}
          >
            ±{size.toFixed(2)}mm
          </button>
        ))}
      </div>

      {/* Adjustment Buttons */}
      <div className={styles.adjustmentRow}>
        <button
          className={styles.downBtn}
          onClick={() => adjustZ(-state.selectedStepSize)}
          disabled={!isPrinting || state.isAdjusting}
        >
          ▼ Lower
        </button>
        <button
          className={styles.upBtn}
          onClick={() => adjustZ(+state.selectedStepSize)}
          disabled={!isPrinting || state.isAdjusting}
        >
          ▲ Raise
        </button>
      </div>

      {/* Manual Input */}
      <div className={styles.manualInputRow}>
        <input
          type="number"
          step="0.01"
          placeholder="±offset (mm)"
          value={manualInput}
          onChange={(e) => setManualInput(e.target.value)}
          onBlur={handleManualAdjust}
          className={styles.manualInput}
          disabled={!isPrinting || state.isAdjusting}
        />
        <button
          className={styles.resetBtn}
          onClick={handleReset}
          disabled={!isPrinting || state.isAdjusting}
        >
          Reset Session
        </button>
      </div>

      {/* Warnings */}
      {warningMessage && <div className={styles.warning}>{warningMessage}</div>}
      {state.errorMessage && <div className={styles.error}>{state.errorMessage}</div>}
    </div>
  );
};

export default ZBabystep;
