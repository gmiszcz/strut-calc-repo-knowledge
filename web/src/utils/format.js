/** Format a USD cost rounded to cents. */
export function fmtCost(usd) {
  return `$${usd.toFixed(2)}`;
}
