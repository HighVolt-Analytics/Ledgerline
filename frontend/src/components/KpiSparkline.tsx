import { Area, AreaChart, ResponsiveContainer } from "recharts";

export function KpiSparkline({ data, color = "hsl(var(--cyan-500))" }: { data: number[]; color?: string }) {
  const chartData = data.map((v, i) => ({ i, v }));
  const gradId = `spark-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <ResponsiveContainer width="100%" height={36}>
      <AreaChart data={chartData} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#${gradId})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
