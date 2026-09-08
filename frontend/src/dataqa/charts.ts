import type { DataQaChartType } from './dataqaClient';

export function toFiniteNumber(value: unknown): number | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && !/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value))
    return null;
  const number = Number(value);
  return Number.isFinite(number) && Math.abs(number) <= Number.MAX_SAFE_INTEGER ? number : null;
}

export function isDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)) return false;
  const date = new Date(value);
  // Reject normalized invalid calendar dates such as February 30.
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && day.toISOString().slice(0, 10) === value.slice(0, 10);
}

export function chartFields(columns: string[], rows: unknown[][]) {
  const dimensions: string[] = [],
    metrics: string[] = [],
    dates: string[] = [];
  if (
    new Set(columns).size !== columns.length ||
    rows.length < 2 ||
    rows.length > 60 ||
    rows.some((row) => row.length !== columns.length)
  )
    return { dimensions, metrics, dates };
  columns.forEach((name, index) => {
    const values = rows.map((row) => row[index]);
    if (values.every((value) => toFiniteNumber(value) !== null)) metrics.push(name);
    if (values.every(isDate)) dates.push(name);
    if (
      values.every(
        (value) =>
          (typeof value === 'string' && value.trim() !== '') ||
          (typeof value === 'number' && Number.isFinite(value))
      ) &&
      new Set(values.map(String)).size === rows.length
    )
      dimensions.push(name);
  });
  return { dimensions, metrics, dates };
}

export function chartData(
  columns: string[],
  rows: unknown[][],
  label: string,
  metric: string,
  type: DataQaChartType
) {
  const fields = chartFields(columns, rows);
  if (!fields.dimensions.includes(label) || !fields.metrics.includes(metric) || label === metric)
    return [];
  const points = rows.map((row) => ({
    label: String(row[columns.indexOf(label)]),
    value: toFiniteNumber(row[columns.indexOf(metric)])!,
  }));
  if (
    type === 'pie' &&
    (points.length > 12 ||
      points.some((point) => point.value < 0) ||
      !points.some((point) => point.value > 0))
  )
    return [];
  if (type === 'line' && fields.dates.includes(label))
    points.sort((a, b) => Date.parse(a.label) - Date.parse(b.label));
  return points;
}

export function formatCell(value: unknown, numeric = false): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  const raw = String(value);
  // Group exact decimal text without converting monetary strings to binary floats.
  if (numeric && /^-?\d+(?:\.\d+)?$/.test(raw)) {
    const [integer, fraction] = raw.split('.');
    return (
      integer!.replace(/\B(?=(\d{3})+(?!\d))/g, ',') +
      (fraction === undefined ? '' : `.${fraction}`)
    );
  }
  return raw;
}
