import { describe, expect, it } from 'vitest';
import { foodGlyph } from './food-icon';

describe('foodGlyph', () => {
  it('prefers the product name over the category', () => {
    expect(foodGlyph('Espresso doppio', 'Getränke', 'product')).toBe('☕');
    expect(foodGlyph('Skyr natural', 'Grundzutaten & Frisches', 'product')).toBe('🥛');
  });

  it('falls back to the category, in German or English', () => {
    expect(foodGlyph('Hausmarke 3000', 'Saucen & Beilagen', 'product')).toBe('🥫');
    expect(foodGlyph('Hausmarke 3000', 'Sauces & sides', 'product')).toBe('🥫');
    expect(foodGlyph('Hausmarke 3000', 'Frischgemüse & Obst', 'product')).toBe('🥦');
  });

  it('falls back to the consumable kind and then to a plate', () => {
    expect(foodGlyph('Sunday batch', null, 'recipe_batch')).toBe('🍲');
    expect(foodGlyph('something at a party', null, 'ad_hoc')).toBe('✎');
    expect(foodGlyph(null, null, 'product')).toBe('🍽');
  });
});
