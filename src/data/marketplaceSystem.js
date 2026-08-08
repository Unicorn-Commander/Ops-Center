// ============================================================================
// MARKETPLACE SYSTEM — the single source of truth shared by BOTH surfaces.
//
// There are two renderers for this page:
//   scripts/generate-marketplace-pages.mjs   the server-rendered files
//   src/pages/public/Marketplace.jsx         the SPA twin at /
//
// Historically they each carried their OWN copy of the crew list, the outcome
// mapping, the headline set, the icon table, and the CSS version string. Ten
// separate constants duplicated across two files, which is exactly how the two
// surfaces drifted: a change would land in one and silently skip the other.
//
// Everything that is not markup lives HERE and is imported by both. If you are
// adding a fact, a count, a colour, or a label, it belongs in this file. The
// renderers should only decide how to draw what this module already decided.
// ============================================================================

import { LISTINGS, PRICE_TBD, SUITE } from './marketplaceListings.js';

// Bump on every stylesheet change. ONE copy, imported by both renderers, so
// the SPA and the SSR pages can never request different cached stylesheets.
// NOTE: marketplace.css must stay hyphen-free in its filename. The backend's
// cache middleware marks any .css path containing a hyphen as immutable for a
// year, so renaming it would freeze it in browsers.
export const CSS_VERSION = '20260808-instrument-8';

export const pad2 = (n) => String(n).padStart(2, '0');

export const accessClass = (access) => (access === 'Available now' ? 'available' : 'development');

// PRICE CONTRACT: null and the {{PRICE_TBD}} placeholder render NOTHING. Not a
// number, not an em-dash, not "Contact us", not an empty element with margin.
// Absence is the design.
export const priceText = (listing) => {
  if (listing.price && listing.price !== PRICE_TBD) return listing.price;
  return '';
};

// Always read the destination from the data. "projectops" resolves and
// "project-ops" returns 404; a hand-typed link eventually hits the wrong one.
export const hostOf = (url) => {
  try { return new URL(url).hostname; } catch { return ''; }
};

// Four mono glyphs. There is no icon library and no emoji on this page.
export const GLYPH = { yes: '●', no: '○', unknown: '—', ext: '↗' };

// THE MAST. One string, rendered statically, identical in the SSR bytes, the
// SPA, the <title>, and og:title.
//
// This used to be a four-item HEADLINES array that both renderers picked from
// at random on every pageview. Three of those four lines were newly written
// here and had never been approved; the approved line showed up on roughly a
// quarter of loads; and the crawled H1 disagreed with the visible H1 the rest
// of the time. One of the invented lines ("Meetings noted. Books closed.")
// also headlined the whole marketplace on closing books while the page itself
// marks Accounting-Ops "In development" — a product claim the page contradicts
// four sections later, on the front door of a page whose thesis is that every
// claim is verified.
//
// If a rotating mast is ever wanted, it needs approved copy AND <title> /
// og:title have to rotate with it. Do not reintroduce an array here.
export const MAST_HEADLINE = 'Put AI to <em>work</em>.';

// The plain-text form, for <title>, og:title, and the SSR/SPA parity test.
export const MAST_HEADLINE_TEXT = 'Put AI to work.';

// ── DEPLOYMENT TARGETS ──────────────────────────────────────────────────────
// Five runtime homes. SELF-HOST is last on purpose: a spec sheet puts the
// conclusion in the terminal column.
export const TARGETS = [
  { id: 'local', label: 'Local', match: (o) => o.startsWith('Local') },
  { id: 'cloud', label: 'Unicorn Cloud', match: (o) => o.startsWith('Unicorn Cloud') },
  { id: 'hybrid', label: 'Hybrid', match: (o) => o.startsWith('Hybrid') },
  { id: 'byok', label: 'BYOK', match: (o) => o.startsWith('BYOK') },
  { id: 'selfhost', label: 'Self-host', match: (o) => o.startsWith('Self-host') },
];

export const supports = (listing, target) => {
  const opts = listing.deployment_options || [];
  if (!opts.length) return 'unknown';
  return opts.some((o) => target.match(o)) ? 'yes' : 'no';
};

export const isSelfHostable = (l) => supports(l, TARGETS[4]) === 'yes';

// Short, honest summary of the egress answer for the ledger column. The full
// sentence is always on the listing page; this never softens it.
export const egressShort = (listing) => {
  const t = (listing.data_egress || '').toLowerCase();
  if (t.startsWith('self-hosted: your data')) return 'Depends on edition';
  if (t.startsWith('yes')) return 'Yes';
  if (t.includes('no.') || t.includes(': no')) return 'Depends on mode';
  return 'See listing';
};

// ── DERIVED COUNTS ──────────────────────────────────────────────────────────
// Every numeral on the page comes from here. Nothing is hand-typed, and the
// browser never counts anything.
export const TOTAL = LISTINGS.length;
export const SELF_HOSTABLE = LISTINGS.filter(isSelfHostable).length;
export const HOSTED = LISTINGS.filter(
  (l) => supports(l, TARGETS[1]) === 'yes' || supports(l, TARGETS[2]) === 'yes'
).length;
export const AVAILABLE = LISTINGS.filter((l) => l.access === 'Available now').length;
export const OPEN_STALLS = 1; // deliberate, and it stays

// ── THE SUITE BUNDLE ────────────────────────────────────────────────────────
// The bundle is the one listing that can lie by omission: it is easy to sell
// eight names and quietly let a reader assume all eight are usable. So the
// "how much of this can I use today" number is DERIVED from the member access
// states (which are themselves derived from each member's own listing), and
// both the index section and the bundle page render this same string.
export const SUITE_MEMBERS = SUITE.members || [];
export const SUITE_TOTAL = SUITE_MEMBERS.length;
export const SUITE_AVAILABLE = SUITE_MEMBERS.filter((m) => m.access === 'Available now').length;
export const SUITE_AVAILABLE_LINE = `${pad2(SUITE_AVAILABLE)} of ${pad2(SUITE_TOTAL)} members are available now. The rest are in development, which is why the Suite is priced but not yet on sale.`;

// ── THE THREE AUDIENCES ─────────────────────────────────────────────────────
// The accent chord IS the audiences: three peers of comparable chroma and
// comparable contrast in both themes. None is "the accent" and the other two
// secondary. Fixed order everywhere (header nav, hero doors, legend, footer
// plinth): buy, publish, host. Three appearances per page.
export const AUDIENCES = [
  {
    id: 'buy',
    tone: '--signal',
    nav: 'Products',
    n: 'No. 01',
    verb: 'Buy an AI employee',
    claim: 'Hire one hosted. It shows up with an account, a credit balance, and a job.',
    proof: `${AVAILABLE} of ${TOTAL} listings available now`,
    cta: 'See the catalog',
    href: '#catalog',
  },
  {
    id: 'publish',
    tone: '--signal-warm',
    nav: 'Publish',
    n: 'No. 02',
    verb: 'Publish your own',
    claim: 'Build on the same identity, credits, gateway, and MCP tools our apps use.',
    proof: `${pad2(OPEN_STALLS)} stall open, and it stays open`,
    cta: 'Become a publisher',
    href: 'https://magicunicorn.dev/book/?product=marketplace-publisher',
  },
  {
    id: 'host',
    tone: '--signal-violet',
    nav: 'Self-host',
    n: 'No. 03',
    verb: 'Host the whole platform',
    // Door 3 carries the most concrete sentence on the page. It must NEVER
    // claim blanket AGPL: Majiks Studio ships Apache-2.0 with no public repo,
    // so a blanket claim would be false, and a false sovereignty claim
    // discredits the one thesis no competing marketplace can match.
    // (Project-Ops was the example here until its public edition was measured
    // and found to be AGPL-3.0 and genuinely public; the rule is unchanged.)
    claim: 'Run every part of this on your own hardware. Every listing states its exact license, and the source link only appears when the repository is actually public.',
    proof: `${SELF_HOSTABLE} of ${TOTAL} self-hostable today`,
    cta: 'What self-hosting takes',
    href: '/marketplace/self-host',
  },
];

// Which columns each audience position lights. Selecting a position
// re-weights the same matrix; it never changes what data exists.
export const LIT = {
  all: TARGETS.map((t) => t.id),
  buy: ['cloud', 'hybrid'],
  publish: ['byok'],
  host: ['local', 'selfhost'],
};

export const TONE_BY_AUDIENCE = Object.fromEntries(AUDIENCES.map((a) => [a.id, a.tone]));

// ── THE READOUT ─────────────────────────────────────────────────────────────
// Computed at build time, inlined as data- attributes, swapped (never counted)
// by the client. Counting is the honesty system; invariance is the argument,
// which is why the HOST caption leads with what does NOT change.
export const READOUTS = {
  all: {
    line: `${pad2(TOTAL)} PRODUCTS · ${pad2(SELF_HOSTABLE)} SELF-HOSTABLE · ${pad2(OPEN_STALLS)} STALL OPEN`,
    caption: 'Every column is shown at equal weight. Pick a position above and the same matrix re-weights: nothing is added, nothing is hidden.',
  },
  buy: {
    line: `${pad2(HOSTED)} / ${pad2(TOTAL)} PRODUCTS RUN HOSTED · ${pad2(AVAILABLE)} AVAILABLE NOW`,
    caption: 'Hosted means we run it: your account, your credit balance, your data under the terms on the listing. Every one of these is on this page with its egress answer in writing.',
  },
  publish: {
    line: `${pad2(OPEN_STALLS)} STALL OPEN · 00 FAKE LISTINGS`,
    caption: 'The empty stall is a row of the ledger, in the table with the shipping products, because publishing is a peer path and not a developer-docs footnote. It stays empty until a real app fills it.',
  },
  host: {
    line: `${pad2(SELF_HOSTABLE)} / ${pad2(TOTAL)} PRODUCTS SELF-HOSTABLE TODAY · ${pad2(OPEN_STALLS)} STALL OPEN`,
    caption: 'Moving to your hardware changes the ground, not the contents: same identity, same gateway, same MCP surface, in your rack. Every listing states its exact license, and no source link is shown unless the repository answers to an anonymous visitor.',
  },
};

// ── THE CREW ────────────────────────────────────────────────────────────────
// Access states mirror the listings. Project-Ops is Available now here because
// it is Available now in the catalog; the two must never disagree.
//
// `plate` is set ONLY for the mascots whose artwork has a BAKED background.
// Verified 2026-08-07 by decoding the served bytes of all six assets:
//
//   center-deep-research  PNG colour-type 2 — no alpha channel  -> plate
//   customer-ops          PNG colour-type 2 — no alpha channel  -> plate
//   majiks-studio         PNG colour-type 2 — no alpha channel  -> plate
//   meeting-ops           RGBA, 71.5% fully transparent, corners (0,0,0,0)
//   project-ops           RGBA, 68.0% fully transparent, corners (0,0,0,0)
//   accounting-ops        RGBA, 58.8% fully transparent, corners (0,0,0,0)
//
// The bottom three are true cutouts and must have NO plate. Meeting-Ops
// carried plate:'#d3d3d3' on the strength of a bad measurement, which painted
// a light-grey slab behind a transparent cutout — one bright box in a row of
// dark ones, on the flagship listing, reading as a broken image rather than a
// choice. Re-decode the bytes before ever adding a plate here.
export const CREW = [
  {
    name: 'Meeting-Ops',
    mascot: '/marketplace/media/mascot-meeting-ops.webp',
    alt: 'The Meeting-Ops scribe, in a camo patrol cap and headset',
    color: '#1b3a6b',
    blurb: 'Captures the conversation, decisions, owners, and due dates.',
    state: 'Available now',
  },
  {
    name: 'Project-Ops',
    mascot: '/marketplace/media/mascot-project-ops.webp',
    // The shipped art is a purple judo gi with a black belt. Both renderers
    // used to say "in beret" here, which describes the Colonel, a different
    // character. The art was right; the words were wrong.
    alt: 'The Project-Ops coordinator, in a purple judo gi and black belt',
    color: '#4f46e5',
    blurb: 'Turns agreed work into owned tasks with status and context.',
    state: 'Available now',
  },
  {
    name: 'Customer-Ops',
    mascot: '/marketplace/media/mascot-customer-ops.webp',
    alt: 'The Customer-Ops account keeper',
    color: '#FF5D73',
    plate: '#0b0c13',
    blurb: 'Keeps the work tied to the customer and the promised outcome.',
    state: 'In development',
  },
  {
    name: 'Accounting-Ops',
    mascot: '/marketplace/media/mascot-accounting-ops.webp',
    alt: 'The Accounting-Ops bookkeeper, bowler hat and brass scale',
    color: '#0f766e',
    blurb: 'Drafts the invoice, traces the posting, and stops for approval where money matters.',
    state: 'In development',
  },
];

export const CREW_NOTE = 'You can use Meeting-Ops and Project-Ops today. The remaining handoffs are in development, so this crew is not presented as an available bundle.';

// The one line that must track the listing count. It is prose, so it spells
// the number, but it is still derived rather than typed.
const WORDS = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
export const PLAIN_TRUTH = `${WORDS[TOTAL] || TOTAL} real products. No empty shelves. No fake popularity contest.`;

// The blocking theme bootstrap. The only surface in this portfolio that
// respects the OS preference AND lets an explicit user choice win, in both
// directions, with no flash of the wrong theme.
export const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem('mu-theme');var d=t||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.dataset.theme=d;document.documentElement.style.colorScheme=d;}catch(e){}})()`;

// ── BETA SIGNUP ─────────────────────────────────────────────────────────────
// An in-development product has no CTA that means anything: there is nothing
// to open, download, or buy. Until now the only thing those rows could offer
// was a link to the build log, and four Listmonk lists sat at zero because no
// surface anywhere submitted to them.
//
// This is the announcement list, and the copy is written so it CANNOT be read
// as availability. Rules it has to keep, in the same spirit as the price
// contract and the empty stall:
//
//   1. The "In development" pill stays, above the form, in the same block.
//   2. No date. Not "soon", not "this quarter", not "early access starts".
//   3. No scarcity. No seat count, no "limited spots", no waitlist position,
//      no subscriber count — a number here would be the fake-popularity
//      signal this page exists to refuse, and the honest number is zero.
//   4. Say what the form does and does not do, in the form, before the field.
//   5. Double opt-in is stated as a fact of the flow, not buried: you are not
//      on the list until you click the link in the mail.
//
// `program` is the server-side allowlist key in backend/beta_signup_api.py.
// The browser cannot name a Listmonk list; it names a programme, and the
// server resolves it.
export const BETA_ENDPOINT = '/api/v1/public/beta/signup';

// Which surfaces carry a form. marketplaceListings.js is GENERATED from
// products-data.js, so this mapping lives here rather than as a hand-added
// field in a generated file.
//
// betaProgramFor() re-reads listing.access instead of trusting this table, so
// flipping a product to "Available now" removes its signup form on the next
// build rather than leaving a "hear about it when it opens" block sitting on
// a shipping product.
export const BETA_PROGRAM_BY_SLUG = {
  'accounting-ops': 'accounting-ops',
};

export const SUITE_BETA_PROGRAM = 'unicorn-commander-suite';

export const betaProgramFor = (listing) => (
  listing && listing.access !== 'Available now'
    ? BETA_PROGRAM_BY_SLUG[listing.slug] || null
    : null
);

export const BETA_COPY = {
  // NOT a second copy of the access pill that sits right under it. The pill
  // carries the state; this line carries what the state MEANS to a reader who
  // came here to buy something. Shipping both as "In development" put the same
  // two words on screen twice, stacked.
  eyebrow: 'There is nothing to buy on this page',
  // Deliberately a verb about being TOLD, not about getting or joining. "Get
  // early access" would be a promise; this is a notification.
  heading: (product) => `Hear about ${product} when it opens`,
  body: (product) => `${product} is not available today. This form does not create an account, reserve a place, start a trial, or grant early access. It adds your address to one announcement list for this product, and nothing else. We have not set a release date, so we are not going to imply one.`,
  optin: 'We will send you a confirmation link. You are not on the list until you click it. Every email carries an unsubscribe link.',
  label: 'Email address',
  button: 'Notify me',
  busy: 'Sending…',
  // The success line is the server's neutral answer: identical whether the
  // address was new, already subscribed, or already confirmed. Anything more
  // specific would make this endpoint an oracle for list membership.
  invalid: 'That does not look like an email address.',
  failed: 'Something went wrong on our end and nothing was recorded. Please try again in a minute.',
  privacy: 'One list, one product. You can unsubscribe from any email we send.',
};

// One implementation, shipped byte-identical to the SSR pages and the SPA, for
// the same reason every other constant in this file is shared: the two
// renderers drift the moment either one carries its own copy.
export const BETA_SIGNUP_SCRIPT = `
      document.querySelectorAll('[data-beta-program]').forEach(function (block) {
        var form = block.querySelector('form');
        var status = block.querySelector('[data-beta-status]');
        var button = block.querySelector('button[type="submit"]');
        if (!form || !status || !button) return;
        form.addEventListener('submit', function (event) {
          event.preventDefault();
          var data = new FormData(form);
          var email = String(data.get('email') || '').trim();
          if (!email || email.indexOf('@') < 1) {
            status.dataset.state = 'error';
            status.textContent = ${JSON.stringify(BETA_COPY.invalid)};
            return;
          }
          var original = button.textContent;
          button.disabled = true;
          button.textContent = ${JSON.stringify(BETA_COPY.busy)};
          status.dataset.state = 'busy';
          status.textContent = '';
          fetch(${JSON.stringify(BETA_ENDPOINT)}, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              program: block.dataset.betaProgram,
              email: email,
              company: String(data.get('company') || '')
            })
          }).then(function (response) {
            return response.json().then(function (payload) { return { ok: response.ok, payload: payload }; });
          }).then(function (result) {
            if (result.ok) {
              status.dataset.state = 'done';
              status.textContent = result.payload.message;
              form.hidden = true;
            } else {
              status.dataset.state = 'error';
              status.textContent = (result.payload && (result.payload.detail || result.payload.message)) || ${JSON.stringify(BETA_COPY.failed)};
              button.disabled = false;
              button.textContent = original;
            }
          }).catch(function () {
            status.dataset.state = 'error';
            status.textContent = ${JSON.stringify(BETA_COPY.failed)};
            button.disabled = false;
            button.textContent = original;
          });
        });
      });`;

export const applyTheme = (next) => {
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  try { localStorage.setItem('mu-theme', next); } catch { /* private mode */ }
};

export const toggleTheme = () => {
  applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
};

export { LISTINGS, PRICE_TBD, SUITE };
