// Thin line icons for rooms, drawn to match the hand-sketched style of the brand set.
// All icons: 48x48 viewBox, stroke only, currentColor.
const wrap = paths => `<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const ROOM_ICONS = {
  // house with a small tree beside it
  external: wrap('<path d="M8 24 21 12l13 12"/><path d="M12 22v16h18V22"/><path d="M18 38v-9h6v9"/><path d="M38 38V30"/><path d="M38 30c-4 0-6-3-5-7 1-3 3-4 5-4s4 1 5 4c1 4-1 7-5 7z"/>'),
  // corridor: door frame with perspective floor line
  hallway: wrap('<path d="M14 40V12h20v28"/><path d="M14 40h20"/><path d="M19 40V18h10v22"/><circle cx="27" cy="29" r="1"/><path d="M6 44 14 40M42 44l-8-4"/>'),
  // cooking pot with steam
  kitchen: wrap('<path d="M10 22h28l-2 16H12z"/><path d="M6 22h36"/><path d="M14 22v-3M34 22v-3"/><path d="M20 14c0-3 3-3 3-6M27 14c0-3 3-3 3-6"/>'),
  // armchair
  living: wrap('<path d="M12 24v-8a4 4 0 0 1 4-4h16a4 4 0 0 1 4 4v8"/><path d="M8 24a3 3 0 0 1 3 3v9h26v-9a3 3 0 0 1 3-3"/><path d="M11 36v4M37 36v4"/><path d="M16 28h16"/>'),
  // bed
  bedroom: wrap('<path d="M8 36V22a2 2 0 0 1 2-2h28a2 2 0 0 1 2 2v14"/><path d="M8 30h32"/><path d="M12 20v-6h24v6"/><path d="M16 14v-3h8v3M8 36v3M40 36v3"/>'),
  // bathtub
  bathroom: wrap('<path d="M8 26h32v4a8 8 0 0 1-8 8H16a8 8 0 0 1-8-8z"/><path d="M12 26V12a3 3 0 0 1 6 0"/><path d="M14 38v3M34 38v3"/><path d="M21 15h6"/>'),
  // generic: tag
  default: wrap('<path d="M10 12h14l14 14-14 14L10 26z"/><circle cx="17" cy="19" r="2"/>'),
};

export function roomIcon(name) {
  const n = name.toLowerCase();
  if (/(external|exterior|outside|garden|front|rear|roof|garage)/.test(n)) return ROOM_ICONS.external;
  if (/(hall|corridor|landing|stairs|entrance|porch)/.test(n)) return ROOM_ICONS.hallway;
  if (/(kitchen|utility|pantry)/.test(n)) return ROOM_ICONS.kitchen;
  if (/(living|lounge|dining|reception|sitting|study|office)/.test(n)) return ROOM_ICONS.living;
  if (/(bed|master|nursery)/.test(n)) return ROOM_ICONS.bedroom;
  if (/(bath|shower|toilet|wc|ensuite|en-suite|cloakroom)/.test(n)) return ROOM_ICONS.bathroom;
  return ROOM_ICONS.default;
}

// App mark: perched parrot, line drawing.
export const PARROT_SVG = `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
<path d="M33 10c-3.5 0-6 3-6 7 0 3 1 5 2.5 7C26 28 23 34 23.5 40c.3 2.5 1.5 4.5 3 6"/>
<path d="M33 10c3.5 0 6.5 2 8 5 2.5 0 4 2 3 4.5-.6 1.5-2 2.2-3 2.5 3 6 2 13-3 22"/>
<path d="M34 10l2-6M36.5 10.5l3-5M39 12l4-4"/>
<circle cx="35.5" cy="16" r="1.3" fill="currentColor" stroke="none"/>
<path d="M30 24c3 6 4 12 3 18"/>
<path d="M36 44l1 5M39.5 43.5l1 5.5"/>
<path d="M30 49.5h19"/>
<path d="M37 49l-2.5 2.5M40.5 49l2.5 2.5"/>
<path d="M25 45L14 60M31 46L24 61M14 60l10 1"/>
</svg>`;

// UI glyphs in the same line style.
const ui = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
export const UI = {
  back: ui('<path d="M19 12H6"/><path d="M11 6l-6 6 6 6"/>'),
  trash: ui('<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>'),
  gear: ui('<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.5 1.5M17.2 17.2l1.5 1.5M5.3 18.7l1.5-1.5M17.2 6.8l1.5-1.5"/>'),
  plus: ui('<path d="M12 5v14M5 12h14"/>'),
  close: ui('<path d="M6 6l12 12M18 6L6 18"/>'),
  check: ui('<path d="M5 12l4 4L19 7"/>'),
  drag: ui('<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01"/>'),
};
