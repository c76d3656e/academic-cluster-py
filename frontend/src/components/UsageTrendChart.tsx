import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { UsageTrend } from '../lib/api'
import { formatNumber } from '../lib/pipeline'

export function UsageTrendChart({ data, height = 220 }: { data: UsageTrend[]; height?: number }) {
  const chartData = data.map((item) => ({
    ...item,
    shortDate: item.date.slice(5),
  }))

  return (
    <div
      className="usage-chart"
      style={{ height }}
      role="img"
      aria-label={`最近 ${data.length} 个数据点的 Token 用量趋势`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 12, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            dataKey="shortDate"
            axisLine={false}
            tickLine={false}
            minTickGap={22}
            tick={{ fill: 'var(--ink-3)', fontSize: 10 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            width={54}
            allowDecimals={false}
            tick={{ fill: 'var(--ink-3)', fontSize: 10 }}
            tickFormatter={(value) => formatNumber(Number(value))}
          />
          <Tooltip
            cursor={{ fill: 'color-mix(in srgb, var(--sage) 12%, transparent)' }}
            contentStyle={{
              color: 'var(--ink)',
              background: 'var(--card-solid)',
              border: '1px solid var(--line)',
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(value) => [formatNumber(Number(value)), 'Token']}
          />
          <Bar dataKey="total_tokens" name="Token" fill="var(--sage-deep)" maxBarSize={28} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
