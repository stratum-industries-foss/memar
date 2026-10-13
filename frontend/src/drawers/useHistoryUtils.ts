/**
 * useHistoryUtils.ts
 * Type definitions and utilities for job history management
 */

export type HistorySortKey = 'name' | 'date' | 'duration' | 'status';

export type JobStatus = 'completed' | 'failed' | 'cancelled' | 'in_progress';

export interface HistoryJob {
  filename: string;
  material?: string;
  startTime: number; // Unix timestamp (ms)
  endTime?: number; // Unix timestamp (ms)
  status: JobStatus;
  result?: string; // summary or error message
  duration?: number; // milliseconds
}

export interface HistoryResponse {
  jobs: HistoryJob[];
  total: number;
  cursor?: string;
}

/**
 * Filter and sort an array of history jobs
 * @param jobs - Array of HistoryJob objects
 * @param statusFilter - Status filter ('all' or specific status value)
 * @param key - Sort key (name, date, duration, or status)
 * @param reverse - If true, reverse the sort order (default: false)
 * @returns Filtered and sorted array of jobs
 */
export function filterAndSortJobs(
  jobs: HistoryJob[],
  statusFilter: string = 'all',
  key: HistorySortKey = 'date',
  reverse: boolean = false
): HistoryJob[] {
  // Filter by status first
  let filtered = jobs;
  if (statusFilter && statusFilter !== 'all') {
    filtered = jobs.filter(job => job.status === statusFilter);
  }

  // Then sort
  const sorted = [...filtered].sort((a, b) => {
    let comparison = 0;

    switch (key) {
      case 'name':
        comparison = a.filename.localeCompare(b.filename);
        break;

      case 'date':
        comparison = a.startTime - b.startTime;
        break;

      case 'duration':
        const durationA = (a.endTime ?? 0) - a.startTime;
        const durationB = (b.endTime ?? 0) - b.startTime;
        comparison = durationA - durationB;
        break;

      case 'status':
        comparison = a.status.localeCompare(b.status);
        break;

      default:
        comparison = 0;
    }

    return reverse ? -comparison : comparison;
  });

  return sorted;
}

/**
 * Calculate duration for a job in milliseconds
 * @param job - HistoryJob object
 * @returns Duration in milliseconds, or 0 if not yet ended
 */
export function getJobDuration(job: HistoryJob): number {
  if (!job.endTime) return 0;
  return job.endTime - job.startTime;
}

/**
 * Format duration in milliseconds to human-readable string
 * @param ms - Duration in milliseconds
 * @returns Formatted string (e.g., "2h 30m 45s")
 */
export function formatDuration(ms: number): string {
  const seconds = Math.floor((ms / 1000) % 60);
  const minutes = Math.floor((ms / (1000 * 60)) % 60);
  const hours = Math.floor(ms / (1000 * 60 * 60));

  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);

  return parts.join(' ');
}

/**
 * Get human-readable status label
 * @param status - JobStatus value
 * @returns Display label
 */
export function getStatusLabel(status: JobStatus): string {
  const labels: Record<JobStatus, string> = {
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
    in_progress: 'In Progress',
  };
  return labels[status] || status;
}
