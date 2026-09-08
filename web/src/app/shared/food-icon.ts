import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/** Keyword → glyph. Product name wins over category, category over the consumable kind. */
const NAME_RULES: readonly [RegExp, string][] = [
  [/kaffee|coffee|espresso|latte/i, '☕'],
  [/\bteea?\b|tee\b|tea\b/i, '🍵'],
  [/wasser|water|schorle/i, '💧'],
  [/energy|monster|cola|limo|soda|saft|juice/i, '🥤'],
  [/\beis\b|ice ?cream|sorbet|gelato/i, '🍨'],
  [/schokolade|chocolate|riegel|\bbar\b|keks|cookie|kuchen|cake|donut/i, '🍫'],
  [/chips|cracker|popcorn|nacho|pretzel|brezel/i, '🍟'],
  [/pizza/i, '🍕'],
  [/burger|cheeseburger/i, '🍔'],
  [/sushi|maki|sashimi/i, '🍣'],
  [/pasta|nudel|noodle|spaghetti|penne/i, '🍝'],
  [/reis\b|rice|risotto/i, '🍚'],
  [/suppe|soup|brühe|bruehe|broth/i, '🍲'],
  [/salat|salad/i, '🥗'],
  [/\bei\b|eier|\begg/i, '🥚'],
  [/hähnchen|haehnchen|chicken|pute|turkey/i, '🍗'],
  [/rind|beef|steak|schwein|pork|schnitzel|hack|wurst|sausage|salami|schinken|ham\b/i, '🥩'],
  [/lachs|salmon|thunfisch|tuna|fisch|fish/i, '🐟'],
  [/käse|kaese|cheese|pecorino|gouda|mozzarella/i, '🧀'],
  [/skyr|quark|joghurt|yogurt|milch|milk|drink.*protein|protein.*shake/i, '🥛'],
  [/beere|berry|himbeer|erdbeer|blaubeer|apfel|apple|banane|banana|obst|fruit|mango/i, '🍓'],
  [/brokkoli|broccoli|gemüse|gemuese|paprika|tomate|gurke|karotte|spinat|zwiebel/i, '🥦'],
  [/brot|bread|baguette|toast|semmel|roll\b|sandwich/i, '🥖'],
  [/butter|margarine|\böl\b|\boel\b|\boil\b|olivenöl/i, '🧈'],
  [/nuss|nüsse|nuesse|mandel|almond|nut\b|samen|seed|lein/i, '🥜'],
  [/senf|mustard|ketchup|mayo|soße|sosse|sauce|dressing|dip/i, '🥫'],
  [/kartoffel|potato|pommes|fries/i, '🥔'],
  [/honig|honey|zucker|sugar|marmelade|jam/i, '🍯'],
  [/bier|beer|wein|wine|whisky|vodka|gin\b/i, '🍺'],
  [/riegel|whey|creatin|kreatin|vitamin|magnesium|supplement/i, '💊'],
];

const CATEGORY_RULES: readonly [RegExp, string][] = [
  [/soße|sosse|sauce|beilage|side/i, '🥫'],
  [/getränk|getraenk|drink|beverage/i, '🥤'],
  [/snack|süß|suess|sweet|candy/i, '🍫'],
  [/brot|back|bread|bakery|pastry/i, '🥖'],
  [/gemüse|gemuese|obst|vegetable|fruit/i, '🥦'],
  [/fertig|convenience|ready|meal/i, '🍱'],
  [/fast.?food|auswärts|auswaerts|restaurant|takeaway|eating out/i, '🍔'],
  [/\btk\b|konserve|frozen|canned|tinned/i, '🧊'],
  [/getreide|reis|hülsen|huelsen|grain|rice|legume|pulse/i, '🍚'],
  [/nuss|nüsse|nuesse|samen|öl|oel|nut|seed|oil/i, '🥜'],
  [/frühstück|fruehstueck|breakfast/i, '🥣'],
  [/supplement|protein/i, '🥛'],
  [/grundzutat|frisch|basic|fresh|staple/i, '🧀'],
];

/** The glyph for one item; exported so tables can use it without the component. */
export function foodGlyph(name: string | null | undefined, category?: string | null, kind?: string | null): string {
  for (const [re, glyph] of NAME_RULES) if (name && re.test(name)) return glyph;
  for (const [re, glyph] of CATEGORY_RULES) if (category && re.test(category)) return glyph;
  if (kind === 'recipe_batch') return '🍲';
  if (kind === 'ad_hoc') return '✎';
  return '🍽';
}

/** Small glyph in front of a logged item, derived from its product and category. */
@Component({
  selector: 'v-food-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="icon" [title]="category() ?? ''" aria-hidden="true">{{ glyph() }}</span>`,
  styles: `.icon { display: inline-block; width: 1.25rem; text-align: center; font-size: 0.95em; line-height: 1; }`,
})
export class FoodIcon {
  readonly name = input<string | null | undefined>(null);
  readonly category = input<string | null | undefined>(null);
  readonly kind = input<string | null | undefined>(null);
  readonly glyph = computed(() => foodGlyph(this.name(), this.category(), this.kind()));
}
