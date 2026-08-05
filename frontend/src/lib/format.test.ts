import { describe, expect, it } from 'vitest';

import {
  formatBytes,
  formatCurrency,
  formatDays,
  formatNumber,
  formatPercent,
  formatPeriod,
  humanizeKey,
  levelFromScore,
  riskTone,
  trendTone,
  truncate,
} from './format';

describe('formatNumber', () => {
  it('renders an em dash for missing values rather than NaN or 0', () => {
    expect(formatNumber(null)).toBe('—');
    expect(formatNumber(undefined)).toBe('—');
    expect(formatNumber(Number.NaN)).toBe('—');
  });

  it('formats zero as a real value, not as missing', () => {
    expect(formatNumber(0)).toBe('0');
  });
});

describe('formatCurrency', () => {
  it('uses compact notation above a thousand', () => {
    expect(formatCurrency(1500)).toBe('$1.5K');
    expect(formatCurrency(2_400_000)).toBe('$2.4M');
    expect(formatCurrency(3_100_000_000)).toBe('$3.1B');
  });

  it('leaves small amounts unabbreviated', () => {
    expect(formatCurrency(940)).toBe('$940');
    expect(formatCurrency(150)).toBe('$150');
  });

  it('keeps cents on sub-dollar figures', () => {
    // Freight per unit is routinely under a dollar; "$0" would read as free.
    expect(formatCurrency(0.41)).toBe('$0.41');
    expect(formatCurrency(1.86)).toBe('$1.86');
  });

  it('still shows a true zero as zero', () => {
    expect(formatCurrency(0)).toBe('$0');
  });

  it('handles negatives without breaking the threshold check', () => {
    expect(formatCurrency(-1500)).toBe('$-1.5K');
  });
});

describe('formatPercent and formatDays', () => {
  it('formats to one decimal by default', () => {
    expect(formatPercent(12.34)).toBe('12.3%');
    expect(formatDays(8.25)).toBe('8.3d');
  });

  it('respects an explicit precision', () => {
    expect(formatPercent(12.34, 0)).toBe('12%');
  });
});

describe('formatBytes', () => {
  it('scales through B, KB and MB', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});

describe('formatPeriod', () => {
  it('turns an ISO month into a short axis label', () => {
    expect(formatPeriod('2024-03')).toBe('Mar 24');
  });

  it('passes through anything that is not year-month', () => {
    expect(formatPeriod('unknown')).toBe('unknown');
  });
});

describe('levelFromScore', () => {
  // These thresholds must stay in step with RiskLevel.from_score on the
  // backend, or a chart and its badge will disagree.
  it('matches the backend thresholds at the boundaries', () => {
    expect(levelFromScore(0)).toBe('LOW');
    expect(levelFromScore(32.9)).toBe('LOW');
    expect(levelFromScore(33)).toBe('MEDIUM');
    expect(levelFromScore(65.9)).toBe('MEDIUM');
    expect(levelFromScore(66)).toBe('HIGH');
    expect(levelFromScore(100)).toBe('HIGH');
  });
});

describe('riskTone', () => {
  it('maps each level to its CSS tone', () => {
    expect(riskTone('HIGH')).toBe('high');
    expect(riskTone('MEDIUM')).toBe('medium');
    expect(riskTone('LOW')).toBe('low');
  });
});

describe('trendTone', () => {
  it('treats a worsening trend as bad and improving as good', () => {
    expect(trendTone('worsening')).toBe('high');
    expect(trendTone('improving')).toBe('low');
    expect(trendTone('stable')).toBe('medium');
    expect(trendTone('insufficient_data')).toBe('neutral');
  });
});

describe('humanizeKey', () => {
  it('turns a snake_case metric key into a label', () => {
    expect(humanizeKey('vendor_concentration')).toBe('Vendor concentration');
  });
});

describe('truncate', () => {
  it('leaves short strings alone', () => {
    expect(truncate('Acme', 10)).toBe('Acme');
  });

  it('adds an ellipsis when clipping', () => {
    expect(truncate('A very long vendor name', 10)).toBe('A very lo…');
  });
});
