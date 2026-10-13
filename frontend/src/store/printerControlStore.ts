import { create } from 'zustand';
import type { FileMetadataColumnKey } from '../drawers/FileMetadataColumns';

interface TemperatureDataPoint {
  timestamp: number;
  nozzle: number;
  bed: number;
  ambient?: number;
}

export interface PrinterControlState {
  // Speed & Flow
  speedByPrinterId: Record<string, number>;
  flowByPrinterId: Record<string, number>;

  // Temperature
  tempChartDataByPrinterId: Record<string, TemperatureDataPoint[]>;
  tempChartRangeByPrinterId: Record<string, number>;

  // Z-Babystep
  zOffsetByPrinterId: Record<string, number>;
  sessionOffsetByPrinterId: Record<string, number>;

  // UI State
  activeDrawer: string | null;
  selectedPrinterId: string | null;
  loadingByPrinterId: Record<string, boolean>;
  errorsByPrinterId: Record<string, string | null>;

  // File Metadata
  visibleFileColumns: Set<FileMetadataColumnKey>;
  fileColumnSortBy: FileMetadataColumnKey | null;
  fileColumnSortAsc: boolean;

  // Actions
  setSpeed: (printerId: string, speed: number) => Promise<void>;
  setFlow: (printerId: string, flow: number) => Promise<void>;
  setBabystep: (printerId: string, delta: number) => Promise<void>;

  setTemperatureChartData: (printerId: string, data: TemperatureDataPoint[]) => void;
  setTemperatureChartRange: (printerId: string, minutes: number) => void;

  setActiveDrawer: (drawer: string | null) => void;
  setSelectedPrinterId: (printerId: string | null) => void;

  toggleFileColumn: (column: FileMetadataColumnKey) => void;
  setFileColumnSort: (column: FileMetadataColumnKey | null, asc?: boolean) => void;

  clearError: (printerId: string) => void;
  setError: (printerId: string, message: string) => void;
}

const STORAGE_KEY = 'memar_printer_control_v1';

const loadFromStorage = (): Partial<PrinterControlState> => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return {
        visibleFileColumns: new Set(parsed.visibleFileColumns || [
          'filename',
          'size',
          'estimatedPrintTime',
        ]),
        fileColumnSortBy: parsed.fileColumnSortBy || 'uploadedAt',
        fileColumnSortAsc: parsed.fileColumnSortAsc ?? false,
      };
    }
  } catch (err) {
    console.error('Failed to load printer control state from storage:', err);
  }
  return {
    visibleFileColumns: new Set(['filename', 'size', 'estimatedPrintTime']),
    fileColumnSortBy: 'uploadedAt',
    fileColumnSortAsc: false,
  };
};

const persistToStorage = (state: PrinterControlState) => {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        visibleFileColumns: Array.from(state.visibleFileColumns),
        fileColumnSortBy: state.fileColumnSortBy,
        fileColumnSortAsc: state.fileColumnSortAsc,
      })
    );
  } catch (err) {
    console.error('Failed to persist printer control state:', err);
  }
};

export const usePrinterControlStore = create<PrinterControlState>()((set, get) => {
  const initialState = loadFromStorage();

  return {
      speedByPrinterId: {},
      flowByPrinterId: {},
      tempChartDataByPrinterId: {},
      tempChartRangeByPrinterId: {},
      zOffsetByPrinterId: {},
      sessionOffsetByPrinterId: {},
      activeDrawer: null,
      selectedPrinterId: null,
      loadingByPrinterId: {},
      errorsByPrinterId: {},
      visibleFileColumns: initialState.visibleFileColumns || new Set(['filename', 'size', 'estimatedPrintTime']),
      fileColumnSortBy: initialState.fileColumnSortBy || 'uploadedAt',
      fileColumnSortAsc: initialState.fileColumnSortAsc ?? false,

      setSpeed: async (printerId: string, speed: number) => {
        set((state: PrinterControlState) => ({
          speedByPrinterId: { ...state.speedByPrinterId, [printerId]: speed },
          loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: true },
        }));

        try {
          const res = await fetch(`/api/printers/${printerId}/gcode/speed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ speed }),
          });

          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.error || 'Failed to set speed');
          }

          set((state: PrinterControlState) => ({
            errorsByPrinterId: { ...state.errorsByPrinterId, [printerId]: null },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
        } catch (err) {
          set((state: PrinterControlState) => ({
            errorsByPrinterId: {
              ...state.errorsByPrinterId,
              [printerId]: (err as Error).message,
            },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
          throw err;
        }
      },

      setFlow: async (printerId: string, flow: number) => {
        set((state: PrinterControlState) => ({
          flowByPrinterId: { ...state.flowByPrinterId, [printerId]: flow },
          loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: true },
        }));

        try {
          const res = await fetch(`/api/printers/${printerId}/gcode/flow`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flow }),
          });

          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.error || 'Failed to set flow');
          }

          set((state: PrinterControlState) => ({
            errorsByPrinterId: { ...state.errorsByPrinterId, [printerId]: null },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
        } catch (err) {
          set((state: PrinterControlState) => ({
            errorsByPrinterId: {
              ...state.errorsByPrinterId,
              [printerId]: (err as Error).message,
            },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
          throw err;
        }
      },

      setBabystep: async (printerId: string, delta: number) => {
        set((state: PrinterControlState) => ({
          loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: true },
        }));

        try {
          const res = await fetch(`/api/printers/${printerId}/gcode/babystep`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delta, absolute: false }),
          });

          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.error || 'Failed to apply babystep');
          }

          const data = await res.json();
          set((state: PrinterControlState) => ({
            zOffsetByPrinterId: { ...state.zOffsetByPrinterId, [printerId]: data.newOffset },
            sessionOffsetByPrinterId: {
              ...state.sessionOffsetByPrinterId,
              [printerId]: data.sessionOffset,
            },
            errorsByPrinterId: { ...state.errorsByPrinterId, [printerId]: null },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
        } catch (err) {
          set((state: PrinterControlState) => ({
            errorsByPrinterId: {
              ...state.errorsByPrinterId,
              [printerId]: (err as Error).message,
            },
            loadingByPrinterId: { ...state.loadingByPrinterId, [printerId]: false },
          }));
          throw err;
        }
      },

      setTemperatureChartData: (printerId: string, data: TemperatureDataPoint[]) => {
        set((state: PrinterControlState) => ({
          tempChartDataByPrinterId: {
            ...state.tempChartDataByPrinterId,
            [printerId]: data,
          },
        }));
      },

      setTemperatureChartRange: (printerId: string, minutes: number) => {
        set((state: PrinterControlState) => ({
          tempChartRangeByPrinterId: {
            ...state.tempChartRangeByPrinterId,
            [printerId]: minutes,
          },
        }));
      },

      setActiveDrawer: (drawer) => set({ activeDrawer: drawer }),

      setSelectedPrinterId: (printerId) => set({ selectedPrinterId: printerId }),

      toggleFileColumn: (column: FileMetadataColumnKey) => {
        set((state: PrinterControlState) => {
          const newColumns = new Set(state.visibleFileColumns);
          if (newColumns.has(column)) {
            newColumns.delete(column);
          } else {
            newColumns.add(column);
          }
          const newState = { visibleFileColumns: newColumns };
          persistToStorage({ ...state, ...newState });
          return newState;
        });
      },

      setFileColumnSort: (column: FileMetadataColumnKey | null, asc = true) => {
        set((state: PrinterControlState) => {
          const newState = {
            fileColumnSortBy: column,
            fileColumnSortAsc: asc,
          };
          persistToStorage({ ...state, ...newState });
          return newState;
        });
      },

      clearError: (printerId: string) => {
        set((state: PrinterControlState) => ({
          errorsByPrinterId: { ...state.errorsByPrinterId, [printerId]: null },
        }));
      },

      setError: (printerId: string, message: string | null) => {
        set((state: PrinterControlState) => ({
          errorsByPrinterId: { ...state.errorsByPrinterId, [printerId]: message },
        }));
      },
    };
});
