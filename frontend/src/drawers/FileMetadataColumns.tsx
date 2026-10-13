import React, { useState, useCallback, useMemo } from 'react';
import styles from './FileMetadataColumns.module.css';

export type FileMetadataColumnKey =
  | 'filename'
  | 'size'
  | 'uploadedAt'
  | 'updatedAt'
  | 'estimatedPrintTime'
  | 'estimatedWeight'
  | 'estimatedCost'
  | 'layerHeight'
  | 'filamentType'
  | 'slicerProfile'
  | 'supportType'
  | 'checksumSHA256';

interface FileMetadataItem {
  id: string;
  filename: string;
  size: number;
  uploadedAt: string;
  updatedAt: string;
  layerHeight?: number;
  nozzleDiameter?: number;
  filamentType?: string;
  estimatedPrintTime?: number;
  estimatedWeight?: number;
  estimatedCost?: number;
  slicerProfile?: string;
  supportType?: string;
  checksumSHA256?: string;
  gcodeFlavor?: string;
}

interface FileMetadataColumnsProps {
  files: FileMetadataItem[];
  printerId: string;
  selectedFileId?: string;
  columns: FileMetadataColumnKey[];
  onColumnToggle?: (column: FileMetadataColumnKey, visible: boolean) => void;
  onSort?: (column: FileMetadataColumnKey, direction: 'asc' | 'desc') => void;
  onFileSelect?: (fileId: string) => void;
  isLoading?: boolean;
  layout?: 'grid' | 'table';
}

interface FileMetadataGridState {
  visibleColumns: Set<FileMetadataColumnKey>;
  sortColumn: FileMetadataColumnKey | null;
  sortDirection: 'asc' | 'desc';
  collapsedRows: Set<string>;
  hoverFileId: string | null;
}

const COLUMN_DEFINITIONS: Record<FileMetadataColumnKey, {
  label: string;
  width: string;
  formatter: (value: any) => string;
  sortable: boolean;
  hideable: boolean;
}> = {
  filename: {
    label: 'Filename',
    width: '200px',
    formatter: (v) => v || '—',
    sortable: true,
    hideable: false,
  },
  size: {
    label: 'Size',
    width: '80px',
    formatter: (bytes) => bytes ? `${(bytes / 1024 / 1024).toFixed(2)} MB` : '—',
    sortable: true,
    hideable: true,
  },
  estimatedPrintTime: {
    label: 'Est. Time',
    width: '100px',
    formatter: (seconds) => {
      if (!seconds) return '—';
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      return `${h}h ${m}m`;
    },
    sortable: true,
    hideable: true,
  },
  estimatedWeight: {
    label: 'Est. Weight',
    width: '100px',
    formatter: (g) => g ? `${g.toFixed(1)}g` : '—',
    sortable: true,
    hideable: true,
  },
  estimatedCost: {
    label: 'Est. Cost',
    width: '80px',
    formatter: (usd) => usd ? `$${usd.toFixed(2)}` : '—',
    sortable: true,
    hideable: true,
  },
  layerHeight: {
    label: 'Layer Height',
    width: '90px',
    formatter: (mm) => mm ? `${(mm * 1000).toFixed(0)}μm` : '—',
    sortable: true,
    hideable: true,
  },
  filamentType: {
    label: 'Filament',
    width: '90px',
    formatter: (v) => v || '—',
    sortable: true,
    hideable: true,
  },
  slicerProfile: {
    label: 'Profile',
    width: '80px',
    formatter: (v) => v || '—',
    sortable: false,
    hideable: true,
  },
  supportType: {
    label: 'Supports',
    width: '80px',
    formatter: (v) => v || 'none',
    sortable: false,
    hideable: true,
  },
  uploadedAt: {
    label: 'Uploaded',
    width: '100px',
    formatter: (iso) => iso ? new Date(iso).toLocaleDateString() : '—',
    sortable: true,
    hideable: true,
  },
  updatedAt: {
    label: 'Modified',
    width: '100px',
    formatter: (iso) => iso ? new Date(iso).toLocaleDateString() : '—',
    sortable: true,
    hideable: true,
  },
  checksumSHA256: {
    label: 'Checksum',
    width: '120px',
    formatter: (v) => v ? `${v.substring(0, 8)}...` : '—',
    sortable: false,
    hideable: true,
  },
};

const FileMetadataColumns: React.FC<FileMetadataColumnsProps> = ({
  files,
  printerId,
  selectedFileId,
  columns,
  onColumnToggle,
  onSort,
  onFileSelect,
  isLoading = false,
  layout = 'grid',
}) => {
  const [state, setState] = useState<FileMetadataGridState>({
    visibleColumns: new Set(columns),
    sortColumn: 'uploadedAt',
    sortDirection: 'desc',
    collapsedRows: new Set(),
    hoverFileId: null,
  });

  const [showColumnMenu, setShowColumnMenu] = useState(false);

  const handleColumnToggle = useCallback((col: FileMetadataColumnKey) => {
    const newColumns = new Set(state.visibleColumns);
    const isVisible = newColumns.has(col);

    if (isVisible) {
      newColumns.delete(col);
    } else {
      newColumns.add(col);
    }

    setState(prev => ({ ...prev, visibleColumns: newColumns }));
    onColumnToggle?.(col, !isVisible);
  }, [state.visibleColumns, onColumnToggle]);

  const handleSort = useCallback((col: FileMetadataColumnKey) => {
    const def = COLUMN_DEFINITIONS[col];
    if (!def.sortable) return;

    const newDirection = state.sortColumn === col && state.sortDirection === 'asc' ? 'desc' : 'asc';
    setState(prev => ({ ...prev, sortColumn: col, sortDirection: newDirection }));
    onSort?.(col, newDirection);
  }, [state.sortColumn, state.sortDirection, onSort]);

  const sortedFiles = useMemo(() => {
    if (!state.sortColumn) return files;

    const col = state.sortColumn;
    return [...files].sort((a, b) => {
      const aVal = (a as any)[col];
      const bVal = (b as any)[col];

      if (aVal === undefined || aVal === null) return 1;
      if (bVal === undefined || bVal === null) return -1;

      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return state.sortDirection === 'asc' ? cmp : -cmp;
    });
  }, [files, state.sortColumn, state.sortDirection]);

  if (isLoading) {
    return (
      <div className={styles.gridContainer} data-testid="metadata-skeleton">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className={styles.skeletonRow} style={{ height: '40px' }} />
        ))}
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>No files uploaded</p>
      </div>
    );
  }

  return (
    <div className={styles.containerOuter}>
      <div className={styles.toolbarRow}>
        <button
          className={styles.columnToggleBtn}
          onClick={() => setShowColumnMenu(!showColumnMenu)}
        >
          ⚙️ Columns
        </button>

        {showColumnMenu && (
          <div className={styles.columnToggleMenu}>
            {Object.entries(COLUMN_DEFINITIONS).map(([key, def]) => {
              if (!def.hideable) return null;
              return (
                <label key={key} className={styles.columnToggleItem}>
                  <input
                    type="checkbox"
                    checked={state.visibleColumns.has(key as FileMetadataColumnKey)}
                    onChange={() => handleColumnToggle(key as FileMetadataColumnKey)}
                  />
                  {def.label}
                </label>
              );
            })}
          </div>
        )}
      </div>

      <div className={styles.gridContainer}>
        {/* Header Row */}
        <div className={styles.gridHeader}>
          {Array.from(state.visibleColumns).map(col => {
            const def = COLUMN_DEFINITIONS[col];
            return (
              <div
                key={col}
                className={styles.gridHeaderCell}
                style={{ minWidth: def.width }}
                onClick={() => handleSort(col)}
                role={def.sortable ? 'button' : 'columnheader'}
              >
                {def.label}
                {state.sortColumn === col && (
                  <span>{state.sortDirection === 'asc' ? ' ↑' : ' ↓'}</span>
                )}
              </div>
            );
          })}
        </div>

        {/* Data Rows */}
        {sortedFiles.map(file => (
          <div
            key={file.id}
            className={`${styles.gridRow} ${selectedFileId === file.id ? styles.selected : ''}`}
            onClick={() => onFileSelect?.(file.id)}
            onMouseEnter={() => setState(prev => ({ ...prev, hoverFileId: file.id }))}
            onMouseLeave={() => setState(prev => ({ ...prev, hoverFileId: null }))}
          >
            {Array.from(state.visibleColumns).map(col => {
              const def = COLUMN_DEFINITIONS[col];
              const value = (file as any)[col];
              return (
                <div
                  key={`${file.id}-${col}`}
                  className={styles.gridCell}
                  style={{ minWidth: def.width }}
                  title={value ? String(value) : ''}
                >
                  {def.formatter(value)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};

export default FileMetadataColumns;
