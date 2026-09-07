<template>
  <section class="dataqa-workbench">
    <header class="dataqa-header">
      <div>
        <span class="panel-eyebrow">Data QA workbench</span>
        <h1>智能问数</h1>
        <p>自然语言直达授权库：生成 SQL 与选表依据，只读执行并可视化。</p>
      </div>
    </header>

    <form class="dataqa-card ask-form" @submit.prevent="ask">
      <label for="dataqa-question">问题</label>
      <div class="ask-row">
        <input
          id="dataqa-question"
          v-model="store.questionDraft"
          maxlength="500"
          placeholder="例如：销量前五的商品是哪些？"
          required
        />
        <button class="primary" type="submit" :disabled="store.busy">开始问数</button>
      </div>
      <p v-if="store.error" class="dataqa-error" role="alert">{{ store.error }}</p>
    </form>

    <div class="dataqa-grid">
      <aside class="dataqa-card query-list">
        <div
          v-for="query in store.queries"
          :key="query.id"
          :class="{ active: query.id === store.selectedId }"
          class="query-item"
        >
          <button type="button" class="query-select" @click="store.select(query.id)">
            <strong>{{ query.question }}</strong>
            <small>{{ query.status }} · {{ formatTime(query.created_at) }}</small>
          </button>
          <button
            type="button"
            class="query-delete"
            :disabled="isQueryActive(query.status) || store.deletingId === query.id"
            :title="isQueryActive(query.status) ? '问数完成后才能删除' : '删除此问数记录'"
            @click="confirmDelete(query.id, query.question)"
          >
            {{ store.deletingId === query.id ? '删除中…' : '删除' }}
          </button>
        </div>
        <p v-if="!store.queries.length && !store.loading">还没有问数记录。</p>
      </aside>

      <main v-if="selected" class="dataqa-detail">
        <article class="dataqa-card">
          <div class="detail-heading">
            <div class="question-row">
              <span class="question-dot"></span>
              <span class="question-text">{{ selected.question }}</span>
            </div>
            <span class="status-chip" :class="selected.status">{{ statusLabel }}</span>
          </div>

          <p v-if="isActive" class="running-hint">
            正在执行：取表结构 → 生成 SQL → 只读执行 → 图表推断，完成后自动展示。
          </p>
          <p v-if="selected.status === 'failed'" class="dataqa-error" role="alert">
            查询失败：{{ selected.error_code || '未知错误' }}
          </p>

          <template v-if="result">
            <!-- 区块二：生成 SQL -->
            <div class="block-heading">
              <span>生成 SQL</span>
              <span class="copy-actions">
                <span v-if="copied" class="copied-tip" role="status">已复制</span>
                <button type="button" class="ghost" title="复制 SQL" @click="copySql">
                  {{ copied ? '已复制' : '复制' }}
                </button>
              </span>
            </div>
            <div class="sql-block">
              <!-- parseMarkdown applies the shared DOMPurify policy before rendering Highlight.js output. -->
              <div class="sql-code" v-html="highlightedSql"></div>
            </div>

            <!-- 区块三：表／字段选择依据 -->
            <div class="block-heading"><span>表／字段选择依据</span></div>
            <div v-for="table in result.tables" :key="table.name" class="rationale-card">
              <div class="rationale-title">
                <span class="table-name">{{ table.name }}</span>
                <span class="table-comment">{{ table.comment }}</span>
              </div>
              <p v-if="table.reason" class="table-reason">{{ table.reason }}</p>
              <div class="chip-row">
                <span class="chip">表分 {{ Math.round(table.score) }}</span>
                <span v-for="field in table.fields" :key="field.name" class="chip">
                  {{ field.name }} · {{ field.comment }}
                </span>
              </div>
            </div>

            <!-- 区块四：图表展示 -->
            <div class="block-heading">
              <span>图表展示</span>
              <select v-model="chartMode" class="chart-select" aria-label="图表类型">
                <option value="auto">自动</option>
                <option value="bar">柱状图</option>
                <option value="line">折线图</option>
                <option value="pie">饼图</option>
                <option value="none">不展示</option>
              </select>
            </div>
            <div v-if="chartType !== 'none' && chartPoints.length" class="chart-box">
              <svg
                :viewBox="`0 0 ${CHART_W} ${CHART_H}`"
                class="chart-svg"
                role="img"
                aria-label="查询结果图表"
              >
                <g v-if="chartType === 'bar'">
                  <line class="chart-axis" x1="0" :y1="CHART_BASE" :x2="CHART_W" :y2="CHART_BASE" />
                  <rect
                    v-for="(point, index) in chartPoints"
                    :key="`bar-${index}`"
                    :x="barX(index)"
                    :y="CHART_BASE - point.height"
                    :width="BAR_W"
                    :height="point.height"
                    rx="3"
                    class="bar"
                  />
                  <text
                    v-for="(point, index) in chartPoints"
                    :key="`bar-value-${index}`"
                    class="value-label"
                    :x="barX(index) + BAR_W / 2"
                    :y="Math.max(CHART_BASE - point.height - 7, 12)"
                    text-anchor="middle"
                  >
                    {{ formatChartValue(point.value) }}
                  </text>
                  <text
                    v-for="(_point, index) in chartPoints"
                    :key="`bar-axis-${index}`"
                    class="axis-label"
                    :x="barX(index) + BAR_W / 2"
                    :y="CHART_BASE + 16"
                    text-anchor="middle"
                  >
                    {{ index + 1 }}
                  </text>
                </g>
                <g v-if="chartType === 'line'">
                  <polyline :points="linePoints" class="line" fill="none" />
                  <g v-for="(point, index) in chartPoints" :key="`line-point-${index}`">
                    <circle
                      :cx="linePointX(index)"
                      :cy="CHART_BASE - point.height"
                      r="4"
                      :fill="PIE_COLORS[index % PIE_COLORS.length]"
                    />
                    <text
                      class="value-label"
                      :x="linePointX(index)"
                      :y="Math.max(CHART_BASE - point.height - 9, 12)"
                      text-anchor="middle"
                    >
                      {{ formatChartValue(point.value) }}
                    </text>
                  </g>
                </g>
                <g v-if="chartType === 'pie'">
                  <path
                    v-for="(arc, index) in pieArcs"
                    :key="`pie-${index}`"
                    :d="arc.path"
                    class="pie-slice"
                    :style="{ '--pie-color': PIE_COLORS[index % PIE_COLORS.length] }"
                  />
                  <text
                    v-for="(arc, index) in pieArcs"
                    v-show="arc.percentage >= 8"
                    :key="`pie-percent-${index}`"
                    class="pie-percent"
                    :x="arc.labelX"
                    :y="arc.labelY"
                    text-anchor="middle"
                  >
                    {{ arc.percentage }}%
                  </text>
                </g>
              </svg>
              <div class="chart-labels">
                <span
                  v-for="(point, index) in chartPoints"
                  :key="`label-${index}`"
                  class="chart-label"
                  :title="`${point.label}：${point.value}`"
                >
                  <span
                    class="legend-dot"
                    :style="{
                      background:
                        chartType === 'bar' ? '#3d8fd1' : PIE_COLORS[index % PIE_COLORS.length],
                    }"
                  ></span>
                  {{ point.label }}：{{ formatChartValue(point.value) }}
                </span>
              </div>
            </div>
            <p v-else class="chart-empty">当前结果形状不适合自动图表。</p>

            <!-- 区块五：查询结果表格 -->
            <div class="block-heading">
              <span>查询结果</span>
              <span class="muted">共 {{ result.row_count }} 条</span>
            </div>
            <div class="table-scroll">
              <table class="result-table">
                <thead>
                  <tr>
                    <th v-for="column in result.columns" :key="column">
                      {{ column }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in result.rows" :key="rowIndex">
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                      {{ formatCell(cell) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 区块六：内容分析 -->
            <div class="block-heading">
              <span>内容分析</span>
              <button
                type="button"
                class="ghost"
                :disabled="store.analysisBusy || result.analysis !== null"
                @click="store.generateAnalysis()"
              >
                {{ store.analysisBusy ? '生成中…' : '生成数据分析' }}
              </button>
            </div>
            <div v-if="result.analysis" class="analysis-text" v-html="analysisHtml"></div>
            <p v-else class="analysis-hint">
              已先返回数据库查询结果。如需趋势、异常和建议，可点击右侧按钮生成分析。
            </p>
          </template>
        </article>
      </main>
      <main v-else class="dataqa-card empty-detail">输入问题开始第一次问数。</main>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useDataQaStore } from '@/stores/dataqa';
import type { DataQaChartType } from '@/dataqa/dataqaClient';
import { parseMarkdown } from '@/utils/markdown';

const store = useDataQaStore();
const chartMode = ref<'auto' | DataQaChartType>('auto');
const copied = ref(false);
let copiedResetTimer: ReturnType<typeof setTimeout> | null = null;

const CHART_W = 640;
const CHART_H = 220;
const CHART_BASE = 200;
const BAR_W = 36;
const PIE_COLORS = ['#185fa5', '#3d8fd1', '#6fb3e0', '#9d8cff', '#8fd1b5', '#d1a26b'];

const selected = computed(() => store.selected);
const result = computed(() => selected.value?.result ?? null);
const highlightedSql = computed(() => {
  const sql = result.value?.sql || '';
  return parseMarkdown(`\`\`\`sql\n${sql}\n\`\`\``);
});
const analysisHtml = computed(() => parseMarkdown(result.value?.analysis ?? ''));
const isActive = computed(() => ['pending', 'running'].includes(selected.value?.status ?? ''));
const statusLabel = computed(() => {
  const map: Record<string, string> = {
    pending: '排队中',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
  };
  return map[selected.value?.status ?? ''] ?? selected.value?.status ?? '';
});

interface ChartPoint {
  label: string;
  value: number;
  height: number;
}

const chartPoints = computed<ChartPoint[]>(() => {
  if (!result.value) return [];
  const { chart, columns, rows } = result.value;
  if (columns.length !== 2) return [];
  const labelIndex = chart.label_field ? columns.indexOf(chart.label_field) : 0;
  const valueIndex = chart.value_field ? columns.indexOf(chart.value_field) : 1;
  if (labelIndex < 0 || valueIndex < 0) return [];
  const numeric = rows.flatMap((row) => {
    const value = toFiniteNumber(row[valueIndex]);
    return value === null ? [] : [{ label: String(row[labelIndex] ?? ''), value }];
  });
  if (!numeric.length) return [];
  const max = Math.max(...numeric.map((point) => point.value), 1);
  return numeric.map((point) => ({
    ...point,
    height: Math.max((point.value / max) * (CHART_BASE - 20), 2),
  }));
});

const autoChartEligible = computed(
  () => chartPoints.value.length >= 2 && chartPoints.value.length <= 60
);

const chartType = computed<DataQaChartType>(() => {
  if (chartMode.value !== 'auto') return chartMode.value;
  const inferred = result.value?.chart.chart_type ?? 'none';
  return inferred === 'none' && autoChartEligible.value ? 'bar' : inferred;
});

const barX = (index: number) => {
  const slot = CHART_W / chartPoints.value.length;
  return index * slot + (slot - BAR_W) / 2;
};

const linePoints = computed(() =>
  chartPoints.value
    .map((point, index) => {
      const slot = CHART_W / chartPoints.value.length;
      const x = index * slot + slot / 2;
      return `${x},${CHART_BASE - point.height}`;
    })
    .join(' ')
);

const linePointX = (index: number) => {
  const slot = CHART_W / chartPoints.value.length;
  return index * slot + slot / 2;
};

const pieArcs = computed(() => {
  const total = chartPoints.value.reduce((sum, point) => sum + Math.abs(point.value), 0);
  if (total <= 0) return [];
  const cx = CHART_W / 2;
  const cy = 110;
  const r = 90;
  let angle = -Math.PI / 2;
  return chartPoints.value.map((point) => {
    const sweep = (Math.abs(point.value) / total) * Math.PI * 2;
    const end = angle + sweep;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(end);
    const y2 = cy + r * Math.sin(end);
    const large = sweep > Math.PI ? 1 : 0;
    const midpoint = angle + sweep / 2;
    const labelRadius = r + 18;
    angle = end;
    return {
      path: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`,
      percentage: Math.round((Math.abs(point.value) / total) * 100),
      labelX: cx + labelRadius * Math.cos(midpoint),
      labelY: cy + labelRadius * Math.sin(midpoint) + 4,
    };
  });
});

const formatCell = (cell: unknown) => {
  if (cell === null || cell === undefined) return '';
  if (typeof cell === 'boolean') return cell ? 'true' : 'false';
  if (typeof cell === 'number') return String(cell);
  if (typeof cell === 'object') return JSON.stringify(cell);
  return String(cell);
};

const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || !value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

const formatChartValue = (value: number) =>
  new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);

const isQueryActive = (status: string) => ['pending', 'running'].includes(status);

const formatTime = (value: string) => {
  if (!value) return '';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
};

async function copySql() {
  if (!result.value?.sql) return;
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(result.value.sql);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = result.value.sql;
      textarea.setAttribute('readonly', '');
      textarea.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
      document.body.append(textarea);
      textarea.select();
      const wasCopied = document.execCommand('copy');
      textarea.remove();
      if (!wasCopied) throw new Error('copy failed');
    }
    copied.value = true;
    if (copiedResetTimer) clearTimeout(copiedResetTimer);
    copiedResetTimer = setTimeout(() => {
      copied.value = false;
      copiedResetTimer = null;
    }, 1500);
  } catch {
    store.error = '复制失败，请手动选择 SQL 文本。';
  }
}

async function ask() {
  await store.ask(store.questionDraft);
}

function confirmDelete(queryId: string, question: string) {
  if (window.confirm(`确定删除「${question}」这条问数记录吗？此操作无法恢复。`)) {
    void store.deleteQuery(queryId);
  }
}

watch(
  () => selected.value?.id,
  () => {
    chartMode.value = 'auto';
  }
);

onMounted(() => store.loadQueries());

onBeforeUnmount(() => {
  if (copiedResetTimer) clearTimeout(copiedResetTimer);
});
</script>

<style scoped>
.dataqa-workbench {
  width: 100%;
  height: 100%;
  overflow: auto;
  padding: 25px;
  color: var(--text, #f7f7fb);
  font-size: var(--font-small);
}
.dataqa-header {
  margin-bottom: 18px;
  padding-bottom: 21px;
  border-bottom: 1px solid var(--line);
}
.dataqa-header h1 {
  margin-top: 5px;
  font-size: 26px;
  letter-spacing: -0.045em;
}
.dataqa-header p {
  margin-top: 7px;
  color: var(--muted);
  font-size: var(--font-caption);
}
.dataqa-grid {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 10px;
}
.dataqa-detail {
  display: grid;
  gap: 10px;
}
.dataqa-card {
  padding: 14px;
  border: 1px solid var(--line-strong, rgba(157, 140, 255, 0.24));
  border-radius: 15px;
  background: var(--surface-strong, rgba(20, 22, 35, 0.9));
  box-shadow: var(--card-shadow, 0 14px 35px rgba(0, 0, 0, 0.12));
}
.query-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-self: start;
}
.query-item {
  position: relative;
}
.query-select {
  width: 100%;
  text-align: left;
  padding: 9px 54px 9px 9px;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.query-select strong {
  font-size: var(--font-caption);
}
.query-item.active .query-select {
  border-color: #8f7cff;
  background: rgba(143, 124, 255, 0.12);
}
.query-select small {
  display: block;
  margin-top: 3px;
  color: var(--muted, #aeb3c2);
  font-size: var(--font-micro);
}
.query-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 3px 6px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  border-radius: 6px;
  background: transparent;
  color: var(--muted, #aeb3c2);
  cursor: pointer;
  font-size: var(--font-micro);
}
.query-delete:hover:not(:disabled),
.query-delete:focus-visible {
  border-color: var(--danger, #ff8a8a);
  color: var(--danger, #ff8a8a);
  outline: none;
}
.query-delete:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.ask-form {
  margin-bottom: 16px;
}
.ask-form label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  font-size: var(--font-caption);
}
.ask-row {
  display: flex;
  gap: 10px;
}
.ask-row input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.15));
  border-radius: 9px;
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
  color: inherit;
  font-size: var(--font-caption);
}
.ask-row input::placeholder {
  color: var(--muted, #8d93a7);
}
.ask-row input:focus {
  border-color: var(--lilac-strong, #8f7cff);
  outline: none;
}
.primary {
  border: 0;
  border-radius: 10px;
  padding: 10px 16px;
  background: #8068ff;
  color: white;
  font-weight: 650;
  font-size: var(--font-caption);
}
.primary:disabled {
  opacity: 0.6;
}
.ghost {
  padding: 4px 10px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: var(--font-micro);
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    color 0.16s ease;
}
.ghost:hover:not(:disabled) {
  border-color: var(--mint-strong, #67d9ad);
  background: var(--surface-hover, rgba(255, 255, 255, 0.07));
  color: var(--text, #f7f7fb);
}
.ghost:focus-visible {
  border-color: var(--mint-strong, #67d9ad);
  outline: 2px solid var(--mint-strong, #67d9ad);
  outline-offset: 2px;
}
.ghost:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.copy-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.copied-tip {
  color: var(--success, #8fd1b5);
  font-size: var(--font-micro);
}
.dataqa-error {
  margin: 8px 0 0;
  color: var(--danger, #ff8a8a);
}
.detail-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.question-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.question-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #3d8fd1;
  flex: none;
}
.question-text {
  font-size: var(--font-ui);
  font-weight: 600;
}
.status-chip {
  padding: 2px 10px;
  border-radius: 10px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  font-size: var(--font-micro);
  white-space: nowrap;
}
.status-chip.completed {
  border-color: rgba(120, 220, 160, 0.6);
  color: var(--success, #8fd1b5);
}
.status-chip.failed {
  border-color: rgba(255, 138, 138, 0.6);
  color: var(--danger, #ff8a8a);
}
.running-hint {
  margin: 0 0 16px;
  color: var(--text-soft, #aeb3c2);
  font-size: var(--font-caption);
}
.block-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 18px 0 8px;
  font-weight: 600;
  font-size: var(--font-body);
}
.block-heading .muted {
  font-weight: 400;
  font-size: var(--font-micro);
  color: var(--muted, #aeb3c2);
}
.sql-block {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(5, 7, 14, 0.72);
  font-family:
    ui-monospace, 'Cascadia Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: var(--font-ui);
  font-weight: 500;
  line-height: 1.7;
  letter-spacing: 0.01em;
  overflow-x: auto;
}
.sql-code :deep(pre) {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.sql-code :deep(code) {
  padding: 0;
  border: 0;
  color: #d7dae5;
  background: transparent;
}
html[data-theme='light'] .sql-block {
  border-color: #e9ebf3;
  color: #293042;
  background: #f0f1f8;
  box-shadow: none;
}
html[data-theme='light'] .sql-code :deep(code) {
  color: #293042;
}
html[data-theme='light'] .sql-code :deep(.hljs-keyword),
html[data-theme='light'] .sql-code :deep(.hljs-selector-tag),
html[data-theme='light'] .sql-code :deep(.hljs-literal) {
  color: #8e79ff;
}
html[data-theme='light'] .sql-code :deep(.hljs-title),
html[data-theme='light'] .sql-code :deep(.hljs-name) {
  color: #2585b8;
}
html[data-theme='light'] .sql-code :deep(.hljs-string) {
  color: #247f6b;
}
html[data-theme='light'] .sql-code :deep(.hljs-number),
html[data-theme='light'] .sql-code :deep(.hljs-attribute) {
  color: #b7791f;
}
.rationale-card {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
  margin-bottom: 8px;
}
.rationale-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}
.table-name {
  font-weight: 600;
}
.table-comment {
  font-weight: 400;
  color: var(--text-soft, #aeb3c2);
}
.table-reason {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--text-soft, #aeb3c2);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 2px 8px;
  border-radius: 10px;
  border: 0.5px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  font-size: 11px;
}
.chart-select {
  padding: 2px 6px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.2));
  border-radius: 6px;
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
  color: inherit;
  font-size: 12px;
}
.chart-box {
  padding: 8px 4px 0;
  border-bottom: 0.5px solid var(--line, rgba(255, 255, 255, 0.15));
}
.chart-svg {
  width: 100%;
  height: 220px;
  display: block;
}
.bar {
  fill: #3d8fd1;
}
.chart-axis {
  stroke: var(--line-strong, rgba(255, 255, 255, 0.25));
  stroke-width: 1;
}
.line {
  stroke: #3d8fd1;
  stroke-width: 2;
}
.value-label,
.axis-label {
  fill: var(--muted, #aeb3c2);
  font-size: 11px;
}
.pie-slice {
  fill: var(--pie-color, #3d8fd1);
  stroke: rgba(0, 0, 0, 0.2);
  stroke-width: 1;
}
.pie-percent {
  fill: var(--text-soft, #aeb3c2);
  font-size: 11px;
  font-weight: 600;
}
.chart-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 6px 0 8px;
}
.chart-label {
  font-size: 11px;
  color: var(--muted, #aeb3c2);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.chart-empty {
  margin: 0;
  font-size: 12px;
  color: var(--muted, #aeb3c2);
}
.table-scroll {
  overflow-x: auto;
}
.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: fixed;
}
.result-table th {
  padding: 6px 8px;
  text-align: left;
  font-weight: 500;
  color: var(--text-soft, #aeb3c2);
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
  border-bottom: 0.5px solid var(--line, rgba(255, 255, 255, 0.15));
}
.result-table td {
  padding: 6px 8px;
  border-bottom: 0.5px solid var(--line, rgba(255, 255, 255, 0.1));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analysis-text {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
}
.analysis-text :deep(p),
.analysis-text :deep(ul),
.analysis-text :deep(ol),
.analysis-text :deep(table) {
  margin: 0 0 10px;
}
.analysis-text :deep(ul),
.analysis-text :deep(ol) {
  padding-left: 20px;
}
.analysis-text :deep(table) {
  width: 100%;
  border-collapse: collapse;
}
.analysis-text :deep(th),
.analysis-text :deep(td) {
  padding: 5px 7px;
  border-bottom: 1px solid var(--line, rgba(255, 255, 255, 0.1));
  text-align: left;
}
.analysis-text :deep(th) {
  color: var(--text-soft, #aeb3c2);
  font-weight: 600;
}
.analysis-text :deep(p:last-child),
.analysis-text :deep(ul:last-child),
.analysis-text :deep(ol:last-child),
.analysis-text :deep(table:last-child) {
  margin-bottom: 0;
}
.analysis-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--muted, #aeb3c2);
}
.empty-detail {
  display: grid;
  place-items: center;
  color: var(--muted, #aeb3c2);
}
</style>
