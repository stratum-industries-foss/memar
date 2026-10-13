import React, { useEffect, useState, Suspense } from 'react';
import { motion } from 'framer-motion';
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { apiFetch } from './api';
import { useScrollReveal, revealVariants, containerVariants, childVariants } from './hooks/useScrollReveal';
import { ShimmerLoader } from './components/ShimmerLoader';
// Lazy-load AnimatedChart to defer motion animation initialization until needed
const AnimatedChart = React.lazy(() => import('./components/AnimatedChart').then(m => ({ default: m.AnimatedChart })));
import styles from './AnalyticsDashboard.module.css';

interface KPIData {
  utilization: { utilization_pct: number; device_count: number };
  oee_trend: Array<{ date: string; oee: number; job_count: number }>;
  error_rate: { error_rate_pct: number; total_jobs: number; failed_jobs: number };
  coolant: { avg_psi: number; min_psi: number; max_psi: number; sample_count: number } | { status: string };
  top_errors: Array<{ mode: string; count: number }>;
}

interface CoolantData {
  devices: Array<{
    device_id: string;
    device_name: string;
    current_psi: number;
    status: string;
    days_to_depletion: number | null;
    alert_triggered: boolean;
  }>;
  critical_count: number;
  declining_count: number;
}

export const AnalyticsDashboard: React.FC = () => {
  const [kpi, setKpi] = useState<KPIData | null>(null);
  const [coolant, setCoolant] = useState<CoolantData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { ref: kpiRef, isInView: kpiInView } = useScrollReveal();
  const { ref: chartRef, isInView: chartInView } = useScrollReveal();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const kpiRes = await apiFetch('/api/analytics/kpi');
        if (!kpiRes.ok) {
          setError(`Analytics unavailable (${kpiRes.status})`);
          return;
        }
        const kpiData = (await kpiRes.json()) as KPIData;
        setKpi(kpiData);
        setError(null);

        // Coolant depletion is supplementary — fail soft so a 404 here
        // doesn't blank the whole dashboard.
        try {
          const coolantRes = await apiFetch('/api/analytics/coolant-depletion');
          if (coolantRes.ok) {
            setCoolant((await coolantRes.json()) as CoolantData);
          } else {
            setCoolant(null);
          }
        } catch {
          setCoolant(null);
        }
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className={styles['analytics-dashboard']} aria-busy="true">
        <h1 className={styles['analytics-title']}>Fleet Analytics Dashboard</h1>
        <p className={styles['analytics-subtitle']}>Real-time fleet metrics and insights</p>
        <ShimmerLoader rows={2} columns={4} height="120px" />
        <ShimmerLoader rows={1} columns={2} height="300px" />
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles['analytics-dashboard']}>
        <div className={`${styles['analytics-status']} ${styles['analytics-status-error']}`}>Error: {error}</div>
      </div>
    );
  }

  if (!kpi) {
    return (
      <div className={styles['analytics-dashboard']}>
        <div className={styles['analytics-status']}>No data available</div>
      </div>
    );
  }

  // Backend returns oee as a fraction (0-1); this view renders percentages, so
  // scale to 0-100 once here for the trend chart, tooltip and the Avg-OEE card.
  const oeeTrend = (kpi.oee_trend ?? []).map((d) => ({ ...d, oee: (d?.oee ?? 0) * 100 }));
  const topErrors = kpi.top_errors ?? [];

  // Average over days that actually had jobs (empty days would drag it to 0).
  const oeeDays = oeeTrend.filter((d) => (d.job_count ?? 0) > 0);
  const avgOee = oeeDays.length > 0
    ? (oeeDays.reduce((s, d) => s + d.oee, 0) / oeeDays.length).toFixed(1)
    : '0';

  const hasCoolantData = kpi.coolant && 'avg_psi' in kpi.coolant;
  const coolantStats = hasCoolantData
    ? kpi.coolant
    : { avg_psi: 0, min_psi: 0, max_psi: 0, sample_count: 0 };

  const utilizationPct = kpi.utilization?.utilization_pct ?? 0;
  const deviceCount = kpi.utilization?.device_count ?? 0;
  const errorRatePct = kpi.error_rate?.error_rate_pct ?? 0;
  const totalJobs = kpi.error_rate?.total_jobs ?? 0;
  const failedJobs = kpi.error_rate?.failed_jobs ?? 0;

  return (
    <div className={styles['analytics-dashboard']}>
      <h1 className={styles['analytics-title']}>Fleet Analytics Dashboard</h1>
      <p className={styles['analytics-subtitle']}>Real-time fleet metrics and insights</p>

      {/* Asymmetric layout: sidebar (KPIs) | main (charts) */}
      <div className={styles['analytics-layout']}>
        {/* Left sidebar: KPI cards */}
        <section className={styles['analytics-sidebar']} role="region" aria-label="Key Performance Indicators">
          <div className={styles['analytics-sidebar-section']}>
            <motion.div
              ref={kpiRef}
              className={styles['analytics-kpi-grid']}
              variants={containerVariants}
              initial="hidden"
              animate={kpiInView ? 'visible' : 'hidden'}
            >
              <div className={`${styles['analytics-card']} ${styles['accent-blue']}`}>
                <div className={styles['analytics-card-label']}>Utilization</div>
                <div className="analytics-card-value value-blue">{utilizationPct.toFixed(1)}%</div>
                <div className={styles['analytics-card-sub']}>{deviceCount} devices</div>
              </div>

              <div className={`${styles['analytics-card']} ${styles['accent-green']}`}>
                <div className={styles['analytics-card-label']}>Avg OEE</div>
                <div className="analytics-card-value value-green">{avgOee}%</div>
                <div className={styles['analytics-card-sub']}>{oeeDays.length} active day{oeeDays.length === 1 ? '' : 's'}</div>
              </div>

              <div className={`${styles['analytics-card']} ${styles['accent-red']}`}>
                <div className={styles['analytics-card-label']}>Error Rate</div>
                <div className="analytics-card-value value-red">{errorRatePct.toFixed(1)}%</div>
                <div className={styles['analytics-card-sub']}>{failedJobs} / {totalJobs}</div>
              </div>

              {hasCoolantData && 'avg_psi' in kpi.coolant && (
                <div className={`${styles['analytics-card']} ${styles['accent-purple']}`}>
                  <div className={styles['analytics-card-label']}>Coolant PSI</div>
                  <div className="analytics-card-value value-purple">{(kpi.coolant.avg_psi ?? 0).toFixed(1)}</div>
                  <div className={styles['analytics-card-sub']}>{kpi.coolant.min_psi ?? 0}-{kpi.coolant.max_psi ?? 0}</div>
                </div>
              )}

              {coolant && (
                <div className={`analytics-card ${(coolant.critical_count ?? 0) > 0 ? 'accent-red' : 'accent-orange'}`}>
                  <div className={styles['analytics-card-label']}>Coolant Status</div>
                  <div className={styles['analytics-card-value']}>
                    <span className={(coolant.critical_count ?? 0) > 0 ? 'value-red' : 'value-orange'}>
                      {coolant.critical_count ?? 0}
                    </span>
                    <span className={styles['value-muted']}> / </span>
                    <span className={styles['value-orange']}>{coolant.declining_count ?? 0}</span>
                  </div>
                  <div className={styles['analytics-card-sub']}>Critical / Declining</div>
                </div>
              )}
            </motion.div>
          </div>

          <div className={styles['analytics-sidebar-section']}>
            <div className={styles['analytics-quickstats']}>
              <div className={styles['analytics-card-label']}>Quick Stats</div>
              <div className={styles['quickstats-list']}>
                <div className={styles['quickstats-row']}>
                  <span className={styles['quickstats-key']}>Total Jobs (24h)</span>
                  <span className={styles['quickstats-val']}>{totalJobs}</span>
                </div>
                <div className={styles['quickstats-row']}>
                  <span className={styles['quickstats-key']}>Success Rate</span>
                  <span className="quickstats-val value-green">
                    {(100 - errorRatePct).toFixed(1)}%
                  </span>
                </div>
                <div className={styles['quickstats-row']}>
                  <span className={styles['quickstats-key']}>Active Devices</span>
                  <span className={styles['quickstats-val']}>{deviceCount}</span>
                </div>
                <div className="quickstats-row quickstats-row-top">
                  <span className="quickstats-key quickstats-key-strong">Last Updated</span>
                  <span className={styles['quickstats-muted']}>{new Date().toLocaleTimeString()}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Right main area: charts */}
        <section className={styles['analytics-main']} role="region" aria-label="Charts and Analytics">
          {/* Charts row */}
          <motion.div
            ref={chartRef}
            className={styles['analytics-chart-grid']}
            variants={containerVariants}
            initial="hidden"
            animate={chartInView ? 'visible' : 'hidden'}
          >
            {/* OEE Trend */}
            <div className={styles['analytics-panel']}>
              <h2 className={styles['analytics-panel-title']}>OEE Trend (7-Day)</h2>
              <Suspense fallback={<ShimmerLoader rows={1} height="300px" />}>
                <AnimatedChart delay={0}>
                  <ResponsiveContainer width="100%" height="300px">
                    <LineChart data={oeeTrend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
                      <XAxis dataKey="date" stroke="var(--border-strong)" />
                      <YAxis domain={[0, 100]} stroke="var(--border-strong)" />
                      <Tooltip
                        contentStyle={{ backgroundColor: 'var(--surface-l1)', border: '1px solid var(--border-default)', borderRadius: '8px', color: 'var(--text-primary)' }}
                        formatter={(value: any) => `${(value as number).toFixed(1)}%`}
                      />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="oee"
                        stroke="var(--color-success)"
                        strokeWidth={2}
                        dot={{ fill: 'var(--color-success)', r: 4 }}
                        activeDot={{ r: 6 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </AnimatedChart>
              </Suspense>
            </div>

            {/* Top Error Modes */}
            <div className={styles['analytics-panel']}>
              <h2 className={styles['analytics-panel-title']}>Top Error Modes</h2>
              {topErrors.length > 0 ? (
                <Suspense fallback={<ShimmerLoader rows={1} height="300px" />}>
                  <AnimatedChart delay={0.1}>
                    <ResponsiveContainer width="100%" height="300px">
                      <BarChart data={topErrors}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
                        <XAxis dataKey="mode" angle={-45} textAnchor="end" height={80} stroke="var(--border-strong)" />
                        <YAxis stroke="var(--border-strong)" />
                        <Tooltip
                          contentStyle={{ backgroundColor: 'var(--surface-l1)', border: '1px solid var(--border-default)', borderRadius: '8px', color: 'var(--text-primary)' }}
                          cursor={{ fill: 'var(--surface-overlay)' }}
                        />
                        <Bar dataKey="count" fill="var(--color-danger)" />
                      </BarChart>
                    </ResponsiveContainer>
                  </AnimatedChart>
                </Suspense>
              ) : (
                <div className={styles['analytics-empty']}>No errors recorded</div>
              )}
            </div>
          </motion.div>

          {/* Coolant Depletion Table */}
          {coolant && (coolant.devices ?? []).length > 0 && (
            <div className={`${styles['analytics-panel']} ${styles['analytics-panel-block']}`}>
              <h2 className={styles['analytics-panel-title']}>Coolant Status by Device</h2>
              <div className={styles['analytics-table-wrap']}>
                <table className={styles['analytics-table']}>
                  <thead>
                    <tr>
                      <th>Device</th>
                      <th>Current PSI</th>
                      <th>Status</th>
                      <th>Days to Change</th>
                      <th>Alert</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(coolant.devices ?? []).map((device) => (
                      <tr key={device.device_id}>
                        <td className="cell-strong">{device.device_name}</td>
                        <td>{(device.current_psi ?? 0).toFixed(1)}</td>
                        <td>
                          <span className={`status-badge ${
                            device.status === 'critical' ? 'status-critical' :
                            device.status === 'declining' ? 'status-declining' :
                            'status-ok'
                          }`}>
                            {(device.status ?? 'unknown').toUpperCase()}
                          </span>
                        </td>
                        <td>
                          {device.days_to_depletion != null
                            ? `${device.days_to_depletion.toFixed(1)} days`
                            : '-'}
                        </td>
                        <td>
                          {device.alert_triggered && (
                            <span className="alert-dot"></span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Utilization Breakdown */}
          <div className={`${styles['analytics-panel']} ${styles['analytics-panel-block']}`}>
            <h2 className={styles['analytics-panel-title']}>Fleet Utilization Breakdown</h2>
            <div className={styles['analytics-breakdown-grid']}>
              <div>
                <div className={styles['analytics-card-label']}>Uptime vs Downtime (24h)</div>
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'Uptime', value: utilizationPct },
                        { name: 'Downtime', value: 100 - utilizationPct }
                      ]}
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      dataKey="value"
                    >
                      <Cell fill="var(--color-success)" />
                      <Cell fill="var(--color-danger)" />
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: 'var(--surface-l1)', border: '1px solid var(--border-default)', borderRadius: '8px', color: 'var(--text-primary)' }}
                      formatter={(value) => `${(value as number).toFixed(1)}%`}
                    />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div>
                <div className={styles['analytics-card-label']}>Jobs by Status</div>
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'Completed', value: totalJobs - failedJobs },
                        { name: 'Failed', value: failedJobs }
                      ]}
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      dataKey="value"
                    >
                      <Cell fill="var(--color-info)" />
                      <Cell fill="var(--color-danger)" />
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: 'var(--surface-l1)', border: '1px solid var(--border-default)', borderRadius: '8px', color: 'var(--text-primary)' }}
                    />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Whitespace block (negative space, desktop only) */}
          <div className={styles['whitespace-block']} aria-hidden="true" />
        </section>
      </div>
    </div>
  );
};

export default AnalyticsDashboard;
