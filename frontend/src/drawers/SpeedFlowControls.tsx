import React, { useState, useCallback } from 'react';
import styles from './SpeedFlowControls.module.css';

interface SpeedFlowControlsProps {
  printerId: string;
  printerName?: string;
  currentSpeed: number;
  currentFlow: number;
  minSpeed?: number;
  maxSpeed?: number;
  minFlow?: number;
  maxFlow?: number;
  isLoading?: boolean;
  onSpeedChange?: (newSpeed: number) => Promise<void>;
  onFlowChange?: (newFlow: number) => Promise<void>;
  onBatchApply?: (speeds: Record<string, number>, flows: Record<string, number>) => Promise<void>;
  enableBatchMode?: boolean;
  theme?: 'light' | 'dark';
}

interface SpeedFlowState {
  speed: number;
  flow: number;
  isDragging: boolean;
  pendingSpeed: number | null;
  pendingFlow: number | null;
  errorMessage: string | null;
  lastUpdateTime: number;
  updateInProgress: boolean;
}

const SpeedFlowControls: React.FC<SpeedFlowControlsProps> = ({
  printerId,
  printerName = 'Printer',
  currentSpeed,
  currentFlow,
  minSpeed = 10,
  maxSpeed = 200,
  minFlow = 10,
  maxFlow = 200,
  isLoading = false,
  onSpeedChange,
  onFlowChange,
  onBatchApply,
  enableBatchMode = false,
  theme = 'dark',
}) => {
  const [state, setState] = useState<SpeedFlowState>({
    speed: currentSpeed,
    flow: currentFlow,
    isDragging: false,
    pendingSpeed: null,
    pendingFlow: null,
    errorMessage: null,
    lastUpdateTime: Date.now(),
    updateInProgress: false,
  });

  const validateSpeed = useCallback((val: number): boolean => {
    return val >= minSpeed && val <= maxSpeed && Number.isInteger(val);
  }, [minSpeed, maxSpeed]);

  const validateFlow = useCallback((val: number): boolean => {
    return val >= minFlow && val <= maxFlow && Number.isInteger(val);
  }, [minFlow, maxFlow]);

  const getSpeedWarning = useCallback((speed: number): string | null => {
    if (speed < 50 || speed > 150) {
      return `Unusual speed value (typical range: 50–150%)`;
    }
    return null;
  }, []);

  const getFlowWarning = useCallback((flow: number): string | null => {
    if (flow < 50 || flow > 150) {
      return `Unusual flow value (typical range: 50–150%)`;
    }
    return null;
  }, []);

  const handleSpeedSliderChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    setState(prev => ({ ...prev, speed: val }));
  }, []);

  const handleSpeedRelease = useCallback(async () => {
    if (!validateSpeed(state.speed)) {
      setState(prev => ({
        ...prev,
        speed: currentSpeed,
        errorMessage: `Speed must be ${minSpeed}–${maxSpeed}%`,
      }));
      return;
    }

    if (state.speed === currentSpeed) return;

    setState(prev => ({ ...prev, updateInProgress: true }));
    try {
      await onSpeedChange?.(state.speed);
      setState(prev => ({ ...prev, errorMessage: null }));
    } catch (err) {
      setState(prev => ({
        ...prev,
        speed: currentSpeed,
        errorMessage: (err as Error).message,
      }));
    } finally {
      setState(prev => ({ ...prev, updateInProgress: false }));
    }
  }, [state.speed, currentSpeed, validateSpeed, minSpeed, maxSpeed, onSpeedChange]);

  const handleFlowSliderChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    setState(prev => ({ ...prev, flow: val }));
  }, []);

  const handleFlowRelease = useCallback(async () => {
    if (!validateFlow(state.flow)) {
      setState(prev => ({
        ...prev,
        flow: currentFlow,
        errorMessage: `Flow must be ${minFlow}–${maxFlow}%`,
      }));
      return;
    }

    if (state.flow === currentFlow) return;

    setState(prev => ({ ...prev, updateInProgress: true }));
    try {
      await onFlowChange?.(state.flow);
      setState(prev => ({ ...prev, errorMessage: null }));
    } catch (err) {
      setState(prev => ({
        ...prev,
        flow: currentFlow,
        errorMessage: (err as Error).message,
      }));
    } finally {
      setState(prev => ({ ...prev, updateInProgress: false }));
    }
  }, [state.flow, currentFlow, validateFlow, minFlow, maxFlow, onFlowChange]);

  const adjustSpeed = useCallback((delta: number) => {
    const newSpeed = Math.max(minSpeed, Math.min(maxSpeed, state.speed + delta));
    setState(prev => ({ ...prev, speed: newSpeed }));
    onSpeedChange?.(newSpeed).catch(() => {
      setState(prev => ({ ...prev, speed: currentSpeed }));
    });
  }, [state.speed, minSpeed, maxSpeed, currentSpeed, onSpeedChange]);

  const adjustFlow = useCallback((delta: number) => {
    const newFlow = Math.max(minFlow, Math.min(maxFlow, state.flow + delta));
    setState(prev => ({ ...prev, flow: newFlow }));
    onFlowChange?.(newFlow).catch(() => {
      setState(prev => ({ ...prev, flow: currentFlow }));
    });
  }, [state.flow, minFlow, maxFlow, currentFlow, onFlowChange]);

  const resetSpeed = useCallback(() => {
    setState(prev => ({ ...prev, speed: 100 }));
    onSpeedChange?.(100);
  }, [onSpeedChange]);

  const resetFlow = useCallback(() => {
    setState(prev => ({ ...prev, flow: 100 }));
    onFlowChange?.(100);
  }, [onFlowChange]);

  const speedWarning = getSpeedWarning(state.speed);
  const flowWarning = getFlowWarning(state.flow);

  return (
    <div className={styles.controlsContainer}>
      {/* Speed Control */}
      <div className={styles.controlGroup}>
        <label>Speed</label>
        <div className={styles.sliderRow}>
          <button onClick={() => adjustSpeed(-5)} disabled={state.updateInProgress}>−</button>
          <input
            type="range"
            min={minSpeed}
            max={maxSpeed}
            value={state.speed}
            onChange={handleSpeedSliderChange}
            onMouseUp={handleSpeedRelease}
            onTouchEnd={handleSpeedRelease}
            className={styles.slider}
            disabled={state.updateInProgress}
          />
          <button onClick={() => adjustSpeed(5)} disabled={state.updateInProgress}>+</button>
        </div>
        <div className={styles.inputRow}>
          <input
            type="number"
            value={state.speed}
            onChange={(e) => setState(prev => ({ ...prev, speed: parseInt(e.target.value, 10) || 100 }))}
            onBlur={handleSpeedRelease}
            className={styles.numberInput}
            disabled={state.updateInProgress}
          />
          <span className={styles.unit}>%</span>
          <button onClick={resetSpeed} disabled={state.updateInProgress}>100%</button>
        </div>
        {speedWarning && <div className={styles.warning}>{speedWarning}</div>}
      </div>

      {/* Flow Control */}
      <div className={styles.controlGroup}>
        <label>Flow</label>
        <div className={styles.sliderRow}>
          <button onClick={() => adjustFlow(-5)} disabled={state.updateInProgress}>−</button>
          <input
            type="range"
            min={minFlow}
            max={maxFlow}
            value={state.flow}
            onChange={handleFlowSliderChange}
            onMouseUp={handleFlowRelease}
            onTouchEnd={handleFlowRelease}
            className={styles.slider}
            disabled={state.updateInProgress}
          />
          <button onClick={() => adjustFlow(5)} disabled={state.updateInProgress}>+</button>
        </div>
        <div className={styles.inputRow}>
          <input
            type="number"
            value={state.flow}
            onChange={(e) => setState(prev => ({ ...prev, flow: parseInt(e.target.value, 10) || 100 }))}
            onBlur={handleFlowRelease}
            className={styles.numberInput}
            disabled={state.updateInProgress}
          />
          <span className={styles.unit}>%</span>
          <button onClick={resetFlow} disabled={state.updateInProgress}>100%</button>
        </div>
        {flowWarning && <div className={styles.warning}>{flowWarning}</div>}
      </div>

      {/* Batch Mode */}
      {enableBatchMode && (
        <div className={styles.batchMode}>
          <button
            className={styles.applyBtn}
            onClick={() => onBatchApply?.({ [printerId]: state.speed }, { [printerId]: state.flow })}
            disabled={state.updateInProgress}
          >
            Apply to All Fleet
          </button>
        </div>
      )}

      {state.errorMessage && <div className={styles.error}>{state.errorMessage}</div>}
    </div>
  );
};

export default SpeedFlowControls;
