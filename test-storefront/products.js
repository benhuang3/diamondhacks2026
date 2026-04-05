// Shared product catalog for Sole Haven demo shoe store.
// Each product's `icon` is an inline SVG so rendering doesn't depend on
// OS emoji fonts.

const SVG = {
  sneaker: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M4 30 L4 22 Q4 18 8 18 L22 18 L30 10 Q32 8 35 9 L44 13 Q48 15 50 19 L54 26 Q58 27 60 30 L60 33 Q60 35 58 35 L6 35 Q4 35 4 33 Z" fill="#2e3a6b" stroke="#1a2347" stroke-width="1.2"/>
    <path d="M22 18 L30 18 L30 26 L22 26 Z" fill="#e8ecff"/>
    <circle cx="12" cy="32" r="2" fill="#fff"/>
    <circle cx="20" cy="32" r="2" fill="#fff"/>
    <circle cx="28" cy="32" r="2" fill="#fff"/>
    <path d="M4 35 L60 35" stroke="#111" stroke-width="2.5" stroke-linecap="round"/>
  </svg>`,
  clog: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M10 28 Q8 20 16 16 L42 14 Q54 13 56 22 L56 30 Q56 34 52 34 L14 34 Q10 34 10 30 Z" fill="#6b7fbf" stroke="#3a4a8a" stroke-width="1.2"/>
    <circle cx="20" cy="20" r="1.6" fill="#1f2b52"/>
    <circle cx="28" cy="18" r="1.6" fill="#1f2b52"/>
    <circle cx="36" cy="18" r="1.6" fill="#1f2b52"/>
    <circle cx="44" cy="20" r="1.6" fill="#1f2b52"/>
    <path d="M10 34 L56 34" stroke="#1a2347" stroke-width="2.5" stroke-linecap="round"/>
  </svg>`,
  trail: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M4 30 L4 23 Q4 19 9 19 L20 18 L28 10 Q31 7 34 9 L46 14 Q51 16 53 21 L57 28 L60 30 L60 33 Q60 35 58 35 L6 35 Q4 35 4 33 Z" fill="#4a6b3a" stroke="#2b3e21" stroke-width="1.2"/>
    <path d="M20 19 L26 19 L26 28 L20 28 Z" fill="#fffbe6"/>
    <path d="M6 35 L60 35" stroke="#111" stroke-width="3" stroke-linecap="round"/>
    <path d="M8 32 L12 32 M16 32 L20 32 M24 32 L28 32 M32 32 L36 32 M40 32 L44 32 M48 32 L52 32" stroke="#111" stroke-width="1.5"/>
  </svg>`,
  flat: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M6 30 Q6 26 12 24 L46 20 Q56 19 58 26 L58 31 Q58 34 54 34 L10 34 Q6 34 6 31 Z" fill="#8b2a4a" stroke="#5a1530" stroke-width="1.2"/>
    <path d="M18 24 Q22 22 28 22" stroke="#fff" stroke-width="1.2" fill="none" opacity="0.6"/>
    <path d="M6 34 L58 34" stroke="#2b0d1a" stroke-width="2" stroke-linecap="round"/>
  </svg>`,
  kids: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M8 30 L8 23 Q8 19 13 19 L26 18 L32 12 Q34 10 37 11 L44 14 Q48 16 50 20 L52 26 Q55 27 56 30 L56 33 Q56 35 54 35 L10 35 Q8 35 8 33 Z" fill="#e85d75" stroke="#a72d44" stroke-width="1.2"/>
    <rect x="15" y="23" width="20" height="3" fill="#fff" rx="1"/>
    <rect x="15" y="27" width="20" height="3" fill="#fff" rx="1"/>
    <path d="M8 35 L56 35" stroke="#4a1520" stroke-width="2.2" stroke-linecap="round"/>
  </svg>`,
  oxford: `<svg viewBox="0 0 64 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M6 30 Q6 24 14 22 L42 18 Q52 17 56 22 L58 30 Q58 34 54 34 L10 34 Q6 34 6 30 Z" fill="#3a2418" stroke="#1a0f07" stroke-width="1.2"/>
    <path d="M22 23 L22 29 M28 22 L28 29 M34 22 L34 29" stroke="#1a0f07" stroke-width="0.8"/>
    <circle cx="24" cy="25" r="0.8" fill="#d4c28a"/>
    <circle cx="30" cy="24" r="0.8" fill="#d4c28a"/>
    <path d="M14 22 Q20 19 30 19" stroke="#1a0f07" stroke-width="1" fill="none"/>
    <path d="M6 34 L58 34" stroke="#000" stroke-width="2.2" stroke-linecap="round"/>
  </svg>`
};

const PRODUCTS = [
  {
    id: "womens-lifestyle-sneakers",
    name: "Women's Lifestyle Sneakers",
    description: "Low-top lifestyle sneakers with cushioned insole and rubber outsole. Everyday comfort in white/gum.",
    price: 79.99,
    icon: SVG.sneaker
  },
  {
    id: "mens-clog-sandals",
    name: "Men's Clog Sandals",
    description: "Waterproof molded clog sandals with massage nodes. Grey, unisex sizing.",
    price: 169.95,
    icon: SVG.clog
  },
  {
    id: "mens-trail-runners",
    name: "Men's Trail Runners",
    description: "Aggressive lug pattern and rock plate for technical trails. Grip on loose gravel and wet roots.",
    price: 139.00,
    icon: SVG.trail
  },
  {
    id: "womens-dress-flats",
    name: "Women's Pointed Flats",
    description: "Italian leather flats with memory-foam insole. Office-ready, work-walking tested.",
    price: 98.00,
    icon: SVG.flat
  },
  {
    id: "kids-velcro-sneakers",
    name: "Kids' Velcro Sneakers",
    description: "Easy on/off velcro closure with reflective heel. Sizes 10C-4Y.",
    price: 44.00,
    icon: SVG.kids
  },
  {
    id: "mens-dress-oxfords",
    name: "Men's Dress Oxfords",
    description: "Full-grain leather cap-toe oxfords with Goodyear welt. Black or oxblood.",
    price: 189.00,
    icon: SVG.oxford
  }
];
