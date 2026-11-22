import { describe, expect, it, vi } from 'vitest';
import { render } from '../../../test/render';
import { TradingViewChart } from './TradingViewChart';
import { EquityChart, DrawdownChart } from '../EquityChart';
import { CompareEquityChart } from '../CompareEquityChart';
import type { EquityPoint } from '../../../types';

describe('TradingView charting components', () => {
  it('TradingViewChart renders, calls onInit, and cleans up on unmount', () => {
    const onInit = vi.fn(() => vi.fn());
    const { container, unmount } = render(
      <TradingViewChart
        height={300}
        testId="test-tv-chart"
        onInit={onInit}
      />,
    );

    const el = container.querySelector('[data-testid="test-tv-chart"]');
    expect(el).not.toBeNull();
    expect(onInit).toHaveBeenCalled();

    const cleanupFn = onInit.mock.results[0].value;
    unmount();
    expect(cleanupFn).toHaveBeenCalled();
  });

  describe('EquityChart', () => {
    const mockData: EquityPoint[] = [
      { date: '2026-01-01', strategy: 10000, benchmark: 10000, drawdown: 0 },
      { date: '2026-01-02', strategy: 10500, benchmark: 10100, drawdown: 0 },
    ];

    it('renders with ready state and correct data attributes', () => {
      const { container } = render(<EquityChart data={mockData} />);
      const chart = container.querySelector('[data-testid="chart-results-equity"]');
      expect(chart).not.toBeNull();
      expect(chart?.getAttribute('data-chart-state')).toBe('ready');
      expect(chart?.getAttribute('data-point-count')).toBe('2');
      expect(chart?.getAttribute('data-first-ts')).toBe('2026-01-01');
      expect(chart?.getAttribute('data-last-ts')).toBe('2026-01-02');
    });

    it('renders empty state when data is empty', () => {
      const { container } = render(<EquityChart data={[]} />);
      const chart = container.querySelector('[data-testid="chart-results-equity"]');
      expect(chart?.getAttribute('data-chart-state')).toBe('empty');
      expect(chart?.getAttribute('data-point-count')).toBe('0');
    });
  });

  describe('DrawdownChart', () => {
    it('renders drawdown chart container', () => {
      const mockData: EquityPoint[] = [
        { date: '2026-01-01', strategy: 10000, benchmark: 10000, drawdown: 0 },
        { date: '2026-01-02', strategy: 9500, benchmark: 10100, drawdown: -5 },
      ];
      const { container } = render(<DrawdownChart data={mockData} />);
      const canvas = container.querySelector('[data-testid="chart-results-drawdown-canvas"]');
      expect(canvas).not.toBeNull();
    });
  });

  describe('CompareEquityChart', () => {
    it('renders aligned comparison curves with correct contract attributes', () => {
      const a = [
        { date: '2026-01-01', strategy: 100 },
        { date: '2026-01-02', strategy: 110 },
      ];
      const b = [
        { date: '2026-01-01', strategy: 200 },
        { date: '2026-01-02', strategy: 220 },
      ];

      const { container } = render(
        <CompareEquityChart a={a} b={b} labelA="Strategy A" labelB="Strategy B" />,
      );

      const chart = container.querySelector('[data-testid="chart-compare-equity"]');
      expect(chart).not.toBeNull();
      expect(chart?.getAttribute('data-chart-state')).toBe('ready');
      expect(chart?.getAttribute('data-series-a-count')).toBe('2');
      expect(chart?.getAttribute('data-series-b-count')).toBe('2');
    });

    it('renders empty state when both series are empty', () => {
      const { container } = render(
        <CompareEquityChart a={[]} b={[]} labelA="A" labelB="B" />,
      );
      const chart = container.querySelector('[data-testid="chart-compare-equity"]');
      expect(chart?.getAttribute('data-chart-state')).toBe('empty');
    });
  });
});
