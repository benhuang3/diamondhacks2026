import type {
  ScanStatus,
  ScanFinding,
  CompetitorJobStatus,
  Report,
  AnnotationsResponse,
} from "./types";

export const DEMO_SCAN_ID_1 = "demo-scan-0001";
export const DEMO_SCAN_ID_2 = "demo-scan-0002";
export const DEMO_COMPETITOR_JOB_ID = "demo-job-0001";
export const DEMO_SCAN_REPORT_ID = "demo-report-scan-0001";
export const DEMO_COMP_REPORT_ID = "demo-report-comp-0001";

const findingsFor = (scanId: string, baseUrl: string): ScanFinding[] => [
  {
    id: `${scanId}-f1`,
    scan_id: scanId,
    selector: "button.checkout-cta",
    xpath: "/html/body/main/section[2]/button",
    bounding_box: { x: 420, y: 610, w: 180, h: 48 },
    severity: "high",
    category: "contrast",
    title: "Checkout CTA fails WCAG contrast",
    description:
      "Primary checkout button uses #c7d2fe on #ffffff (contrast ratio 2.1:1), below WCAG AA 4.5:1 for normal text.",
    suggestion:
      "Darken the button background to #4338ca or increase text weight and add a 1px border for additional definition.",
    page_url: baseUrl,
  },
  {
    id: `${scanId}-f2`,
    scan_id: scanId,
    selector: "img.hero-banner",
    xpath: "/html/body/main/section[1]/img",
    bounding_box: { x: 0, y: 80, w: 1280, h: 420 },
    severity: "medium",
    category: "a11y",
    title: "Hero image missing descriptive alt text",
    description:
      "The above-the-fold hero image has an empty alt attribute, hiding key promotional context from assistive technologies.",
    suggestion:
      "Provide alt text describing the product and offer, e.g. 'Spring sale — 30% off all running shoes'.",
    page_url: baseUrl,
  },
  {
    id: `${scanId}-f3`,
    scan_id: scanId,
    selector: "nav.primary a[href='/sale']",
    xpath: "/html/body/header/nav/a[3]",
    bounding_box: { x: 640, y: 24, w: 72, h: 32 },
    severity: "low",
    category: "nav",
    title: "Sale link lacks focus outline",
    description:
      "Keyboard focus style has been removed via `outline: none` with no replacement ring, hurting keyboard navigability.",
    suggestion:
      "Add `:focus-visible { outline: 2px solid #4f46e5; outline-offset: 2px; }` to the nav anchor.",
    page_url: baseUrl,
  },
  {
    id: `${scanId}-f4`,
    scan_id: scanId,
    selector: "form#newsletter input[type='email']",
    xpath: "/html/body/footer/form/input[1]",
    bounding_box: { x: 120, y: 1820, w: 320, h: 40 },
    severity: "medium",
    category: "ux",
    title: "Newsletter field missing label association",
    description:
      "Email field uses placeholder-only labeling. On focus the hint disappears, and screen readers announce an unlabeled field.",
    suggestion:
      "Add a visually-hidden <label for='email'> element or use aria-label='Email address'.",
    page_url: baseUrl,
  },
];

export const DEMO_SCAN_STATUS_1: ScanStatus = {
  scan_id: DEMO_SCAN_ID_1,
  status: "done",
  progress: 1,
  url: "https://demo-storefront.example.com",
  findings_count: 4,
  report_id: DEMO_SCAN_REPORT_ID,
  error: null,
};

export const DEMO_SCAN_STATUS_2: ScanStatus = {
  scan_id: DEMO_SCAN_ID_2,
  status: "running",
  progress: 0.55,
  url: "https://another-shop.example.com",
  findings_count: 2,
  report_id: null,
  error: null,
};

export const DEMO_SCAN_FINDINGS_1 = findingsFor(
  DEMO_SCAN_ID_1,
  "https://demo-storefront.example.com",
);
export const DEMO_SCAN_FINDINGS_2 = findingsFor(
  DEMO_SCAN_ID_2,
  "https://another-shop.example.com",
);

export const DEMO_ANNOTATIONS_1: AnnotationsResponse = {
  scan_id: DEMO_SCAN_ID_1,
  url: "https://demo-storefront.example.com",
  annotations: DEMO_SCAN_FINDINGS_1,
};

export const DEMO_SCAN_REPORT: Report = {
  report_id: DEMO_SCAN_REPORT_ID,
  kind: "scan",
  parent_id: DEMO_SCAN_ID_1,
  scores: { accessibility: 68, ux: 74, flow: 81 },
  summary:
    "The storefront is structurally sound but has several accessibility gaps that materially impact conversion. The checkout CTA contrast issue is the highest-priority fix — it likely suppresses click-through on assistive technology and low-vision users.",
  sections: [
    {
      title: "Accessibility Snapshot",
      body: "4 findings identified across contrast, alt-text, focus, and labeling. No blocking WCAG Level A violations, but 1 AA contrast failure is affecting the primary CTA.",
    },
    {
      title: "User Flow",
      body: "Navigation is conventional and scannable. Focus styles are partially suppressed in the top nav, limiting keyboard discoverability of the 'Sale' entry point.",
    },
  ],
  recommendations: [
    "Fix checkout CTA contrast immediately (highest conversion leverage).",
    "Add descriptive alt text to hero image and other promotional media.",
    "Restore :focus-visible outlines on all navigation links.",
    "Associate form labels via <label for> or aria-label for newsletter capture.",
  ],
};

export const DEMO_COMPETITOR_JOB: CompetitorJobStatus = {
  job_id: DEMO_COMPETITOR_JOB_ID,
  status: "done",
  progress: 1,
  store_url: "https://demo-storefront.example.com",
  competitors: [
    {
      id: "c1",
      job_id: DEMO_COMPETITOR_JOB_ID,
      name: "Your Store",
      url: "https://demo-storefront.example.com",
      price: 49.99,
      shipping: 6.99,
      tax: 4.12,
      discount: null,
      checkout_total: 61.1,
      notes: "Baseline checkout with no auto-applied promo.",
    },
    {
      id: "c2",
      job_id: DEMO_COMPETITOR_JOB_ID,
      name: "Northwind Goods",
      url: "https://northwind.example.com",
      price: 44.99,
      shipping: 0,
      tax: 3.71,
      discount: "FREESHIP",
      checkout_total: 48.7,
      notes: "Free shipping promo auto-applied at cart.",
    },
    {
      id: "c3",
      job_id: DEMO_COMPETITOR_JOB_ID,
      name: "Contoso Outfitters",
      url: "https://contoso.example.com",
      price: 52.0,
      shipping: 4.99,
      tax: 4.29,
      discount: "SAVE5",
      checkout_total: 56.28,
      notes: "SAVE5 code surfaced in exit-intent popup.",
    },
  ],
  report_id: DEMO_COMP_REPORT_ID,
  error: null,
};

export const DEMO_COMPETITOR_REPORT: Report = {
  report_id: DEMO_COMP_REPORT_ID,
  kind: "competitors",
  parent_id: DEMO_COMPETITOR_JOB_ID,
  scores: { pricing: 62, value: 58, experience: 77 },
  summary:
    "Your checkout total lands $12.40 above the cheapest competitor. Shipping is the dominant delta — 2 of 3 competitors offer conditional free shipping that your store does not match.",
  sections: [
    {
      title: "Price Positioning",
      body: "List price is mid-market. After shipping & tax your total is the highest in the comparison set.",
    },
    {
      title: "Promo & Discount Surfacing",
      body: "Competitors surface codes aggressively (exit-intent, cart banners). Your store only exposes discounts at the footer newsletter.",
    },
  ],
  recommendations: [
    "Introduce a free-shipping threshold at $50 to match Northwind Goods.",
    "A/B test an exit-intent SAVE5 promo mirroring Contoso's offer surface.",
    "Add price-comparison schema.org markup to improve SERP price display.",
  ],
};

export const DEMO_RECENT_SCANS: ScanStatus[] = [
  DEMO_SCAN_STATUS_1,
  DEMO_SCAN_STATUS_2,
];
