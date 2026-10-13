type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  component: string;
  message: string;
  data?: any;
}

const logs: LogEntry[] = [];
const MAX_LOGS = 500;

function formatLog(level: LogLevel, component: string, message: string, data?: any): string {
  const timestamp = new Date().toISOString();
  const prefix = `[${timestamp}] [${level}] [${component}]`;
  const dataStr = data ? ` | ${JSON.stringify(data)}` : '';
  return `${prefix} ${message}${dataStr}`;
}

// In production builds the console output and the free-form `data` payload are
// suppressed (import.meta.env.DEV is false): the in-memory ring buffer still
// records level/component/message, but no PII-bearing data leaks to the console
// or the buffer. In dev everything is retained for debugging.
export function debug(component: string, message: string, data?: any) {
  const safeData = import.meta.env.DEV ? data : undefined;
  const entry: LogEntry = { timestamp: new Date().toISOString(), level: 'DEBUG', component, message, data: safeData };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift();
  if (import.meta.env.DEV) console.debug(formatLog('DEBUG', component, message, data));
}

export function info(component: string, message: string, data?: any) {
  const safeData = import.meta.env.DEV ? data : undefined;
  const entry: LogEntry = { timestamp: new Date().toISOString(), level: 'INFO', component, message, data: safeData };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift();
  if (import.meta.env.DEV) console.log(formatLog('INFO', component, message, data));
}

export function warn(component: string, message: string, data?: any) {
  const safeData = import.meta.env.DEV ? data : undefined;
  const entry: LogEntry = { timestamp: new Date().toISOString(), level: 'WARN', component, message, data: safeData };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift();
  if (import.meta.env.DEV) console.warn(formatLog('WARN', component, message, data));
}

export function error(component: string, message: string, data?: any) {
  const safeData = import.meta.env.DEV ? data : undefined;
  const entry: LogEntry = { timestamp: new Date().toISOString(), level: 'ERROR', component, message, data: safeData };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift();
  if (import.meta.env.DEV) console.error(formatLog('ERROR', component, message, data));
}

export function getLogs(): string {
  return logs.map(l => formatLog(l.level, l.component, l.message, l.data)).join('\n');
}

export function downloadLogs() {
  const content = getLogs();
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `memar-frontend-${new Date().toISOString().split('T')[0]}.log`;
  a.click();
  URL.revokeObjectURL(url);
}

export function clearLogs() {
  logs.length = 0;
}
