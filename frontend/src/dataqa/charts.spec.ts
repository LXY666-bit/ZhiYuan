import { describe, expect, it } from 'vitest';
import { chartData, chartFields, formatCell, isDate, toFiniteNumber } from './charts';

describe('query result display', () => {
  it('switches independent metrics without mutating the table', () => {
    const columns = ['region', 'sales', 'orders'];
    const rows = [
      ['East', '1234.50', 5],
      ['West', '987.00', 3],
    ];
    expect(chartFields(columns, rows).metrics).toEqual(['sales', 'orders']);
    expect(chartData(columns, rows, 'region', 'orders', 'bar').map((p) => p.value)).toEqual([5, 3]);
    expect(rows[0]).toEqual(['East', '1234.50', 5]);
    expect(formatCell('12345678901234567890.0120', true)).toBe('12,345,678,901,234,567,890.0120');
    expect(formatCell('00123')).toBe('00123');
  });

  it('orders temporal charts and keeps original table order', () => {
    const rows = [
      ['2026-03-01', 3],
      ['2026-01-01', 1],
    ];
    expect(chartData(['date', 'sales'], rows, 'date', 'sales', 'line').map((p) => p.value)).toEqual(
      [1, 3]
    );
    expect(rows[0]?.[1]).toBe(3);
    expect(isDate('2026-02-30')).toBe(false);
    expect(isDate('2026-99-99')).toBe(false);
  });

  it('preserves negative and zero values and rejects misleading pies', () => {
    const rows = [
      ['East', -3],
      ['West', 0],
    ];
    expect(
      chartData(['region', 'sales'], rows, 'region', 'sales', 'bar').map((p) => p.value)
    ).toEqual([-3, 0]);
    expect(chartData(['region', 'sales'], rows, 'region', 'sales', 'pie')).toEqual([]);
    expect(
      chartData(
        ['region', 'sales'],
        [
          ['a', 0],
          ['b', 0],
        ],
        'region',
        'sales',
        'pie'
      )
    ).toEqual([]);
  });

  it('rejects incomplete, ambiguous, oversized and unsafe numeric data', () => {
    for (const rows of [
      [
        ['a', 1],
        ['b', null],
      ],
      [
        ['a', 1],
        ['a', 2],
      ],
      [['a'], ['b', 2]],
    ]) {
      expect(chartData(['region', 'sales'], rows, 'region', 'sales', 'bar')).toEqual([]);
    }
    expect(
      chartFields(
        ['a', 'a'],
        [
          [1, 2],
          [3, 4],
        ]
      ).metrics
    ).toEqual([]);
    expect(
      chartFields(
        ['a', 'b'],
        Array.from({ length: 61 }, (_, i) => [String(i), i])
      ).metrics
    ).toEqual([]);
    for (const value of [true, '', 'NaN', 'Infinity', '0x10', '001', '9007199254740993'])
      expect(toFiniteNumber(value)).toBeNull();
  });
});
