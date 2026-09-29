// SPDX-License-Identifier: MIT
export type RGB = readonly [number, number, number];

export const parseHex = (hex: string): RGB => {
  const raw = hex.replace(/^#/, '');
  const full = /^[\da-f]{3}$/i.test(raw)
    ? raw.split('').map((c) => c + c).join('')
    : raw;
  if (!/^[\da-f]{6}$/i.test(full)) return [46, 134, 222];
  return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16)];
};

export const mix = (a: RGB, b: RGB, amount: number): RGB => {
  const t = Math.max(0, Math.min(1, amount));
  const channel = (i: number) => Math.round(a[i] * (1 - t) + b[i] * t);
  return [channel(0), channel(1), channel(2)];
};

export const rgba = (color: RGB, alpha = 1): string =>
  `rgba(${color.join(',')},${Math.max(0, Math.min(1, alpha))})`;

export const palette = (brand: string, accent = '#F5C3C6') => {
  const base = parseHex(brand);
  return {brand: base, tint: mix(base, [255, 255, 255], 0.45), accent: parseHex(accent)};
};
