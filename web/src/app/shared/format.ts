import { Pipe, PipeTransform } from '@angular/core';
import { BandZone, LineItem, MacroKey, Quality } from '../api';
import { isoDayIn } from '../core/format.service';
import { storedLocale } from '../core/format.service';

/** kcal as integer, salt with two decimals, everything else one decimal. */
/**
 * A number in the tenant's own convention: 1.234,5 in German, 1,234.5 in English (R69).
 *
 * These formatters are called from templates as plain functions, so they read the locale
 * mirrored into browser storage rather than injecting the service that owns it.
 */
function decimal(value: number, digits: number): string {
  return value.toLocaleString(storedLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatMacro(value: number | null | undefined, key: MacroKey): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  const digits = key === 'kcal' ? 0 : key === 'salt' ? 2 : 1;
  return decimal(value, digits);
}

export function formatKg(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return decimal(value, digits);
}

/** An amount as the ledger writes it: a whole number stays whole, a fraction keeps one place. */
export function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return decimal(value, Number.isInteger(value) ? 0 : 1);
}

/**
 * The unit an item was logged in, with the portion when the unit alone is ambiguous.
 *
 * One unit can have several portions — a piece of egg is S, M, L or XL — so "1 piece" would
 * stand for anything between 43 and 65 g. `t` translates; the caller owns the dictionary.
 */
export function formatUnit(it: LineItem, t: (text: string) => string): string {
  const unit = t(it.unit_code ?? it.base_unit);
  const label = it.portion_label;
  // a label that only repeats the unit's own word would read "1 piece (piece)"
  return label && label !== it.unit_code ? `${unit} (${t(label)})` : unit;
}

export function formatSigned(value: number | null | undefined, digits = 1, unit = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return `${value > 0 ? '+' : ''}${decimal(value, digits)}${unit ? ' ' + unit : ''}`;
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
    const d = new Date(`${iso}T00:00:00Z`);
    return d.toLocaleDateString(storedLocale(), {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }
}

/** The ISO day an instant falls on, in the configured zone (R69). */
export function isoDate(d: Date): string {
  return isoDayIn(d);
}

export function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}
