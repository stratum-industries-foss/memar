import React, { useState, useCallback, useMemo } from 'react';
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Brush,
} from 'recharts';
import styles from './TemperatureChart.module.css';

interface TemperatureDataPoint {
  timestamp: number;
  nozzle: number;
  bed: number;
  ambient?: number;
}

interface TemperatureChartProps {
  printerId: string;
  printerName?: string;
  chartType: 'realtime' | 'history';
  dataPoints: TemperatureDataPoint[];
  isLoading?: boolean;
  onZoom?: (startTime: number, endTime: number) => void;
  onRangeChange?: (mins: number) => void;
  maxDataPoints?: number;
  autoUpdate?: boolean;
  theme?: 'light' | 'dark';
}

interface TemperatureChartState {
  selectedRange: number;
  isZoomed: boolean;
  zoomWindow: [number, number] | null;
  hoveredDataPoint: TemperatureDataPoint | null;
  tooltipPosition: { x: number; y: number } | null;
}

const TemperatureChart: React.FC<TemperatureChartProps> = ({
  printerId,
  printerName = 'Printer',
  chartType,
  dataPoints,
  isLoading = false,
  onZoom,
  onRangeChange,
  maxDataPoints = 600,
  autoUpdate = true,
  theme = 'dark',
}) => {
  const [state, setState] = useState<TemperatureChartState>({
    selectedRange: 60,
    isZoomed: false,
    zoomWindow: null,
    hoveredDataPoint: null,
    tooltipPosition: null,
  });

  const handleRangeClick = useCallback((mins: number) => {
    setState(prev => ({
      ...prev,
      selectedRange: mins,
      isZoomed: false,
      zoomWindow: null,
    }));
    onRangeChange?.(mins);
  }, [onRangeChange]);

  const displayData = useMemo(() => {
    if (dataPoints.length === 0) return [];

    // Downsample if needed
    const step = Math.max(1, Math.ceil(dataPoints.length / maxDataPoints));
    return dataPoints.filter((_, i) => i % step === 0);
  }, [dataPoints, maxDataPoints]);

  const yMin = useMemo(() => {
    if (displayData.length === 0) return 0;
    const minTemp = Math.min(...displayData.map(d => d.nozzle || d.bed || 0));
    return Math.max(0, Math.floor(minTemp - 10));
  }, [displayData]);

  const yMax = useMemo(() => {
    if (displayData.length === 0) return 300;
    const maxTemp = Math.max(...displayData.map(d => d.nozzle || 0));
    return Math.ceil(maxTemp + 10);
  }, [displayData]);

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  if (isLoading) {
    return (
      <div className={styles.chartContainer} data-testid="temperature-chart">
        <h3>{printerName} - Temperature</h3>
        <div className={styles.skeleton} data-testid="temp-chart-skeleton">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className={styles.skeletonLine} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.chartContainer} data-testid="temperature-chart">
      <h3>{printerName} - Temperature</h3>

      {displayData.length > 0 ? (
        <ResponsiveContainer width="100%" height={240} data-testid="recharts-wrapper">
          <ComposedChart
            data={displayData}
            margin={{ top: 20, right: 30, left: 0, bottom: 60 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
            <XAxis
              dataKey="timestamp"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={formatTime}
              angle={-45}
              height={60}
            />
            <YAxis
              domain={[yMin, yMax]}
              label={{ value: '°C', angle: -90, position: 'insideLeft' }}
            />
            <Tooltip
              contentStyle={{
                background: 'rgba(0, 0, 0, 0.9)',
                border: '1px solid #4ECDC4',
                borderRadius: '4px',
              }}
              formatter={(value: any) => value?.toFixed(1)}
              labelFormatter={(label) => new Date(label).toLocaleString()}
            />
            <Line
              dataKey="nozzle"
              stroke="#FF6B6B"
              dot={false}
              isAnimationActive={chartType === 'realtime'}
              animationDuration={chartType === 'realtime' ? 0 : 300}
            />
            <Line
              dataKey="bed"
              stroke="#4ECDC4"
              dot={false}
              isAnimationActive={chartType === 'realtime'}
              animationDuration={chartType === 'realtime' ? 0 : 300}
            />
            {displayData.some(d => d.ambient) && (
              <Line
                dataKey="ambient"
                stroke="#95A5A6"
                strokeDasharray="5 5"
                dot={false}
                isAnimationActive={false}
              />
            )}
            <Brush
              dataKey="timestamp"
              height={30}
              travellerWidth={8}
              data-testid="recharts-brush"
            />
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ padding: '40px', textAlign: 'center', color: '#999' }}>
          No temperature data available
        </div>
      )}

      <div className={styles.rangeButtons}>
        {[15, 30, 60, 120].map(mins => (
          <button
            key={mins}
            className={`${styles.rangeBtn} ${state.selectedRange === mins ? styles.active : ''}`}
            onClick={() => handleRangeClick(mins)}
          >
            {mins} min
          </button>
        ))}
      </div>
    </div>
  );
};

export default TemperatureChart;
