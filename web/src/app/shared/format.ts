import { Pipe, PipeTransform } from '@angular/core';
import { BandZone, MacroKey, Quality } from '../api';

/** kcal as integer, salt with two decimals, everything else one decimal. */
export function formatMacro(value: number | null | undefined, key: MacroKey): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  const digits = key === 'kcal' ? 0 : key === 'salt' ? 2 : 1;
  return value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatKg(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatSigned(value: number | null | undefined, digits = 1, unit = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  const s = value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${value > 0 ? '+' : ''}${s}${unit ? ' ' + unit : ''}`;
}

export const ZONE_LABEL: Record<BandZone, string> = {
  below_min: 'below minimum',
  below_optimum: 'below optimum',
  optimal: 'in the optimal range',
  above_optimum: 'above optimum',
  above_max: 'above maximum',
};

/** Colour class for a band zone or quality grade; only these five words ever colour the UI. */
export function toneOf(z: BandZone | Quality | null | undefined): 'ok' | 'warn' | 'bad' | 'muted' {
  switch (z) {
    case 'optimal':
    case 'green':
      return 'ok';
    case 'below_optimum':
    case 'above_optimum':
    case 'yellow':
      return 'warn';
    case 'below_min':
    case 'above_max':
    case 'red':
      return 'bad';
    default:
      return 'muted';
  }
}

@Pipe({ name: 'macro' })
export class MacroPipe implements PipeTransform {
  transform(value: number | null | undefined, key: MacroKey): string {
    return formatMacro(value, key);
  }
}

@Pipe({ name: 'kg' })
export class KgPipe implements PipeTransform {
  transform(value: number | null | undefined, digits = 1): string {
    return formatKg(value, digits);
  }
}

@Pipe({ name: 'signed' })
export class SignedPipe implements PipeTransform {
  transform(value: number | null | undefined, digits = 1, unit = ''): string {
    return formatSigned(value, digits, unit);
  }
}

@Pipe({ name: 'dayName' })
export class DayNamePipe implements PipeTransform {
  transform(iso: string | null | undefined): string {
    if (!iso) return '';
    const d = new Date(`${iso}T00:00:00`);
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  }
}

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}
