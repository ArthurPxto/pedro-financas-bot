const brl = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

export const money = (n: number): string => brl.format(n);

export const plural = (n: number, one: string, many: string): string =>
  `${n} ${n === 1 ? one : many}`;

/** "2026-06" -> "jun 2026". Outras chaves voltam como vieram. */
export function monthLabel(key: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(key);
  if (!m) return key;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, 1);
  const label = date.toLocaleDateString("pt-BR", { month: "short", year: "numeric" });
  return label.replace(".", "");
}
