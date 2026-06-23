<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/i18n'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import type { ChartProps, ChartSeries, ChartDataPoint } from './types'

// 注册 ECharts 组件
use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
])

const props = withDefaults(defineProps<ChartProps>(), {
  height: 300,
  showLegend: true,
  showGrid: true,
  showTooltip: true,
  animate: true,
  responsive: true,
  colors: () => [
    '#5470c6',
    '#91cc75',
    '#fac858',
    '#ee6666',
    '#73c0de',
    '#3ba272',
    '#fc8452',
    '#9a60b4',
    '#ea7ccc',
  ],
  formatValue: undefined,
  onPointClick: undefined,
})

const { t } = useI18n()

// 计算图表选项
const chartOption = computed(() => {
  const baseOption = {
    tooltip: {
      show: props.showTooltip,
      trigger: props.type === 'pie' || props.type === 'donut' ? 'item' : 'axis',
    },
    legend: {
      show: props.showLegend,
      bottom: 0,
    },
    animation: props.animate,
    responsive: props.responsive,
  }

  if (props.type === 'pie' || props.type === 'donut') {
    return {
      ...baseOption,
      series: [
        {
          type: 'pie',
          radius: props.type === 'donut' ? ['40%', '70%'] : '50%',
          data: props.data[0]?.data.map((point, index) => ({
            name: point.label,
            value: point.value,
            itemStyle: {
              color: point.color || props.colors[index % props.colors.length],
            },
          })),
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)',
            },
          },
        },
      ],
    }
  }

  if (props.type === 'bar' || props.type === 'line' || props.type === 'area') {
    const categories = props.data[0]?.data.map((point) => point.label) || []
    const series = props.data.map((s, index) => ({
      name: s.name,
      type: props.type === 'area' ? 'line' : props.type,
      data: s.data.map((point) => point.value),
      itemStyle: {
        color: s.color || props.colors[index % props.colors.length],
      },
      areaStyle: props.type === 'area' ? {} : undefined,
      smooth: true,
    }))

    return {
      ...baseOption,
      xAxis: {
        type: 'category',
        data: categories,
        show: props.showGrid,
      },
      yAxis: {
        type: 'value',
        show: props.showGrid,
      },
      series,
    }
  }

  return {}
})

// 处理点击事件
function handleClick(params: any) {
  if (!props.onPointClick) return

  const seriesIndex = params.seriesIndex || 0
  const dataIndex = params.dataIndex || 0

  const series = props.data[seriesIndex]
  const point = series?.data[dataIndex]

  if (series && point) {
    props.onPointClick(point, series)
  }
}
</script>

<template>
  <Card>
    <CardHeader v-if="title || description">
      <div>
        <CardTitle v-if="title">{{ title }}</CardTitle>
        <CardDescription v-if="description">{{ description }}</CardDescription>
      </div>
    </CardHeader>
    <CardContent>
      <div :style="{ height: `${height}px` }">
        <VChart
          :option="chartOption"
          :style="{ height: '100%', width: '100%' }"
          autoresize
          @click="handleClick"
        />
      </div>
    </CardContent>
  </Card>
</template>
