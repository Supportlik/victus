/** Series colours shared by every chart (dataviz palette). Order matters: first is the primary series. */
export const CHART_PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#4a3aa7'] as const;

export const ZONE_COLOR = {
  below_min: '#eb6834',
  below_optimum: '#eda100',
  optimal: '#1baf7a',
  above_optimum: '#eda100',
  above_max: '#eb6834',
} as const;
