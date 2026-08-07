// The SPA twin of the server-rendered marketplace.
//
// This component and scripts/generate-marketplace-pages.mjs render the SAME
// page in the SAME stylesheet. Everything that is not markup — the crew, the
// audiences, the deployment targets, the readout strings, the counts, the CSS
// version, the theme bootstrap — comes from src/data/marketplaceSystem.js,
// which both surfaces import. Do not reintroduce a local copy of any of it:
// duplicated constants are exactly how these two files drifted before.
//
// Structural note: there is no React route for /marketplace or
// /marketplace/<slug>. Those are server-only surfaces, served straight from
// public/marketplace/. This component is mounted by RootRedirect at "/" for
// logged-out humans, so it renders the index only. The listing detail pages
// and /marketplace/self-host exist as prerendered files.

import { useEffect, useMemo, useState } from 'react';
import { LISTINGS, SUITE } from '../../data/marketplaceListings.js';
import {
  AUDIENCES, CREW, CREW_NOTE, CSS_VERSION, GLYPH, HEADLINES, LIT, PLAIN_TRUTH,
  READOUTS, TARGETS, TONE_BY_AUDIENCE, accessClass, egressShort, hostOf, pad2,
  supports, toggleTheme,
} from '../../data/marketplaceSystem.js';

// ── SHARED FRAGMENTS ────────────────────────────────────────────────────────

// The plate. Three of the six approved mascots have a BAKED background (0.0%
// transparency): they are illustrated scenes, not cutouts. A hairline frame
// plus an honest inner fill reads as glass in a frame, so the defect becomes
// architecture. Uniform outer geometry with honest inner fill is what makes
// six mascots with three different alpha conventions read as one crew.
// Do NOT "fix" this later by cropping the baked assets.
function Plate({ src, alt, size = 96 }) {
  return (
    <div className="plate">
      <img src={src} alt={alt || ''} loading="lazy" width={size} height={size} />
    </div>
  );
}

function PartNo({ part, license }) {
  return <span className="partno mono">{part} · {(license || '').toUpperCase()}</span>;
}

function brandVars(listing) {
  const style = {};
  if (listing.brand_primary) style['--b'] = listing.brand_primary;
  if (listing.brand_accent || listing.brand_primary) style['--ba'] = listing.brand_accent || listing.brand_primary;
  if (listing.plate) style['--plate'] = listing.plate;
  return style;
}

// The outbound cell prints its own destination. Never a generic "Learn more",
// and the hostname always comes from the data so the projectops/project-ops
// hyphen trap cannot be reintroduced by hand.
function Hostname({ href, className = '' }) {
  return (
    <a className={`hostname ${className}`.trim()} href={href}>
      {hostOf(href)}<span className="arrow" aria-hidden="true">{GLYPH.ext}</span>
    </a>
  );
}

// ── PAGE ────────────────────────────────────────────────────────────────────

export default function Marketplace() {
  const [headline] = useState(() => HEADLINES[Math.floor(Math.random() * HEADLINES.length)]);
  // "all" is the served default: every column lit, nothing selected. The
  // legend is not a filter and never removes a product.
  const [audience, setAudience] = useState('all');
  const [swapping, setSwapping] = useState(false);

  useEffect(() => {
    document.title = 'Put AI to work | Unicorn Commander Marketplace';
    let stylesheet = document.getElementById('marketplace-instrument-css');
    if (!stylesheet) {
      stylesheet = document.createElement('link');
      stylesheet.id = 'marketplace-instrument-css';
      stylesheet.rel = 'stylesheet';
      stylesheet.href = `/marketplace/marketplace.css?v=${CSS_VERSION}`;
      document.head.appendChild(stylesheet);
    }
    return () => stylesheet?.remove();
  }, []);

  const lit = LIT[audience] || LIT.all;
  const tone = TONE_BY_AUDIENCE[audience];
  const readout = READOUTS[audience] || READOUTS.all;

  const choose = (id) => {
    // Selecting the active position returns to the all-lit state, so there is
    // always a way back to the full grid without a reload.
    const next = audience === id ? 'all' : id;
    setSwapping(true);
    window.setTimeout(() => { setAudience(next); setSwapping(false); }, 180);
  };

  // Cell styling mirrors the SSR script exactly: lit columns take the
  // audience's chord colour, everything else drops back. Nothing is added or
  // hidden — the matrix is re-weighted, not filtered.
  const cellProps = (colId, selfHostYes) => {
    const on = lit.includes(colId);
    const active = audience !== 'all';
    const cls = ['mcell'];
    if (active && on) cls.push('is-lit');
    if (active && !on) cls.push('is-dim');
    // Machined hatch: the visual signature of self-host.
    if (selfHostYes && audience === 'host') cls.push('hatch-on');
    const style = {};
    if (tone && on) { style['--tone'] = `var(${tone})`; style['--tone-ch'] = `var(${tone}-ch)`; }
    return { className: cls.join(' '), style, 'data-col': colId };
  };

  const sourceColClass = audience === 'host' ? 'col-source license is-lit' : 'col-source license';
  const sourceColStyle = audience === 'host' ? { '--tone': 'var(--signal-violet)' } : undefined;

  const openIndex = useMemo(() => pad2(LISTINGS.length + 1), []);

  return (
    <div className="marketplace-page">
      <header className="site-header">
        <div className="shell">
          <a className="brand" href="/marketplace">
            <img src="/logos/uc-mark-colonel.webp" alt="" width="30" height="30" />
            <span>Unicorn Commander</span>
          </a>
          {/* Audience order invariant: buy, publish, host. Same three, same
              order, in header, hero, and footer. */}
          <nav className="nav" aria-label="Primary">
            <a className="aud-buy" href="#catalog">Products</a>
            <a className="aud-publish" href="#catalog">Publish</a>
            <a className="aud-host" href="/marketplace/self-host">Self-host</a>
            <a href="#platform">The platform</a>
            <a href="/auth/login">Sign in</a>
            <button className="theme-toggle" type="button" onClick={toggleTheme} aria-label="Switch colour theme">Theme</button>
          </nav>
        </div>
      </header>

      <main>
        <section className="hero">
          <div className="shell hero-inner">
            <div className="hero-copy">
              <p className="eyebrow">The Unicorn Commander marketplace</p>
              <h1 className="mast" dangerouslySetInnerHTML={{ __html: headline }} />
              <p className="lede hero-claim">Tell us the job. Take home finished work from AI employees and creator tools that run on infrastructure you can own.</p>
              <p className="small">{PLAIN_TRUTH}</p>
            </div>
            <img
              className="colonel"
              src="/logos/The_Colonel.png"
              alt="The Colonel, the Unicorn Commander mark: a white unicorn in a navy beret with a rainbow mane and a gold horn"
              width="288"
              height="288"
            />
          </div>
        </section>

        {/* 01 — the three doors. Equality is structural: one shared subgrid
            track set, so enlarging one option visibly breaks all three. */}
        <section className="section-block" id="audiences" aria-labelledby="audiences-title">
          <div className="shell railed">
            <span className="rail-num">01</span>
            <h2 className="section-title" id="audiences-title">Three ways in.<br />All of them real.</h2>
            <div className="triptych">
              {AUDIENCES.map((a) => (
                <a className="door" key={a.id} href={a.href} style={{ '--door': `var(${a.tone})` }}>
                  <span className="door-n">{a.n}</span>
                  <h3 className="door-verb">{a.verb}</h3>
                  <p className="door-claim">{a.claim}</p>
                  <p className="door-proof">{a.proof}</p>
                  <span className="door-cta">{a.cta} {GLYPH.ext}</span>
                </a>
              ))}
            </div>

            <div className="legend">
              <p className="eyebrow">Which of these three are you?</p>
              <div className="legend-control" role="group" aria-label="Audience">
                {AUDIENCES.map((a) => (
                  <button
                    key={a.id}
                    className="legend-btn"
                    type="button"
                    aria-pressed={audience === a.id}
                    onClick={() => choose(a.id)}
                    style={{ '--tone': `var(${a.tone})`, '--tone-ch': `var(${a.tone}-ch)` }}
                  >
                    {a.verb}
                  </button>
                ))}
              </div>
              <p className="small">This is a legend, not a filter. It never removes a product. It tells you what the three colours on this page mean.</p>
            </div>
          </div>
        </section>

        {/* 02 — the ledger. The catalog is a table, not a card grid. */}
        <section className="section-block" id="catalog" aria-labelledby="catalog-title">
          <div className="shell railed">
            <span className="rail-num">02</span>
            <h2 className="section-title" id="catalog-title">Choose the work,<br />not the software.</h2>
            <p className="lede">Each row says where the product runs, what license it ships under, and whether your data leaves. Open a listing for its verified capabilities and approval boundaries.</p>

            <div className="ledger-scroll">
              <table className="ledger">
                <caption className="sr-only">Every product listed on the Unicorn Commander marketplace, with its access state, runtimes, source license, and data-egress answer.</caption>
                <thead>
                  <tr>
                    <th className="colhead" scope="col">#<span className="colhead-note">index, not rank</span></th>
                    <th className="colhead" scope="col"><span className="sr-only">Character art</span></th>
                    <th className="colhead" scope="col">Product</th>
                    <th className="colhead" scope="col">Access</th>
                    <th className="colhead col-runs" scope="col">Runs where</th>
                    <th className="colhead col-source" scope="col">Source</th>
                    <th className="colhead col-egress" scope="col">Data leaves</th>
                    <th className="colhead" scope="col"><span className="sr-only">Go to product</span></th>
                  </tr>
                </thead>
                <tbody>
                  {LISTINGS.map((l, i) => (
                    <tr key={l.slug} style={brandVars(l)}>
                      <td className="cell-index"><span className="chip" aria-hidden="true" />{pad2(i + 1)}</td>
                      <td className="cell-art">
                        <Plate src={l.mascot} alt={l.mascot_alt} />
                        <PartNo part={l.part} license={l.source_license} />
                      </td>
                      <td className="cell-name">
                        <h3 className="product-name"><a href={`/marketplace/${l.slug}`}>{l.name}</a></h3>
                        <p className="row-tagline">{l.tagline}</p>
                        <p className="row-subline mono">
                          {(l.deployment_options || []).join(' · ')} | {l.source_license} | Data leaves: {egressShort(l)}
                        </p>
                      </td>
                      <td><span className={`pill pill-${accessClass(l.access)}`}>{l.access}</span></td>
                      <td className="col-runs">
                        <ul className="runs-list">
                          {(l.deployment_options || []).map((o) => (
                            <li key={o} className={o.startsWith('Self-host') ? 'is-selfhost' : undefined}>{o}</li>
                          ))}
                        </ul>
                      </td>
                      {/* Source is a permanent column at the same weight as
                          Access, never a footer badge. The LINK appears only
                          when the repo answered 200 to an anonymous fetch. */}
                      <td className={sourceColClass} style={sourceColStyle}>
                        {l.source_url
                          ? <a href={l.source_url}>{l.source_license}</a>
                          : <>{l.source_license}<br /><a className="micro" href="/marketplace/self-host">Self-host guide</a></>}
                      </td>
                      <td className="col-egress">{egressShort(l)}</td>
                      <td className="cell-action">
                        <Hostname href={l.cta.href} />
                        <a className="btn btn-secondary" href={`/marketplace/${l.slug}`}>{l.cta.label}</a>
                      </td>
                    </tr>
                  ))}

                  {/* The open stall is a row of the ledger, in the table with
                      the shipping products, because publishing is a peer path
                      and not a developer-docs footnote. */}
                  <tr className="row-open" style={{ '--b': 'var(--signal-warm)' }}>
                    <td className="cell-index"><span className="chip" aria-hidden="true" />{openIndex}</td>
                    <td className="cell-art">
                      <div className="plate"><span aria-hidden="true">+</span></div>
                      <span className="partno mono">UC-{openIndex} · YOUR LICENSE</span>
                    </td>
                    <td className="cell-name">
                      <h3 className="product-name">This spot is for your app</h3>
                      <p className="row-tagline">The stalls are real products only, which is why one of them is empty. It stays empty until a real app fills it.</p>
                    </td>
                    <td><span className="pill pill-open">Open</span></td>
                    <td className="col-runs"><ul className="runs-list"><li>{GLYPH.unknown}</li></ul></td>
                    <td className={sourceColClass} style={sourceColStyle}>{GLYPH.unknown}</td>
                    <td className="col-egress">{GLYPH.unknown}</td>
                    <td className="cell-action">
                      <a className="publish-link" href="https://magicunicorn.dev/book/?product=marketplace-publisher">Publish on UC {GLYPH.ext}</a>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* 03 — the signature moment. Same fleet, different axis. */}
        <section className="section-block" id="deployment" aria-labelledby="deployment-title">
          <div className="shell railed">
            <span className="rail-num">03</span>
            <h2 className="section-title" id="deployment-title">Where it runs.<br />Your call.</h2>
            <p className="lede">The same fleet, viewed along a different axis. {GLYPH.yes} supported, {GLYPH.no} not supported, {GLYPH.unknown} unverified.</p>

            <div className="matrix-scroll">
              <table className="matrix">
                <caption className="sr-only">Deployment matrix: which runtime homes each product supports. Filled circle means supported, hollow circle means not supported, dash means unverified.</caption>
                <thead>
                  <tr>
                    <th className="colhead" scope="col">#</th>
                    <th className="colhead" scope="col">Product</th>
                    {TARGETS.map((t) => {
                      const on = lit.includes(t.id);
                      const active = audience !== 'all';
                      return (
                        <th
                          key={t.id}
                          className={`colhead${active && on ? ' is-lit' : ''}${active && !on ? ' is-dim' : ''}`}
                          scope="col"
                          data-col={t.id}
                          style={tone && on ? { '--tone': `var(${tone})` } : undefined}
                        >
                          {t.label}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {LISTINGS.map((l, i) => (
                    <tr key={l.slug} style={brandVars(l)}>
                      <td className="cell-index"><span className="chip" aria-hidden="true" />{pad2(i + 1)}</td>
                      <th scope="row">{l.name}</th>
                      {TARGETS.map((t) => {
                        const s = supports(l, t);
                        return (
                          <td key={t.id} {...cellProps(t.id, t.id === 'selfhost' && s === 'yes')}>
                            <span className="sr-only">{s === 'yes' ? 'Supported' : s === 'no' ? 'Not supported' : 'Unverified'}</span>
                            <span aria-hidden="true">{GLYPH[s]}</span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  <tr className="row-open" style={{ '--b': 'var(--signal-warm)' }}>
                    <td className="cell-index"><span className="chip" aria-hidden="true" />{openIndex}</td>
                    <th scope="row">This spot is for your app</th>
                    {TARGETS.map((t) => (
                      <td key={t.id} {...cellProps(t.id, false)}>
                        <span className="sr-only">Unverified</span>
                        <span aria-hidden="true">{GLYPH.unknown}</span>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Every string here was computed at build time from the listing
                records. The client only swaps between them: it never counts,
                and no number ever animates upward from zero. */}
            <p className={`readout mono${swapping ? ' swapping' : ''}`}>{readout.line}</p>
            <p className={`readout-caption${swapping ? ' swapping' : ''}`}>{readout.caption}</p>
          </div>
        </section>

        <section className="section-block" id="platform" aria-labelledby="platform-title">
          <div className="shell railed">
            <span className="rail-num">04</span>
            <h2 className="section-title" id="platform-title">An ecosystem,<br />not a catalog.</h2>
            <p className="lede">Identity, credits, the model gateway, and MCP tools are the ground. Our apps stand on it today. The stalls are real products only, which is why one of them is empty.</p>
            <div className="platform-rail">
              <p className="eyebrow">The Unicorn Commander platform</p>
              <div className="rail-cells">
                <span className="rail-cell">Identity + SSO</span>
                <span className="rail-cell">Credits + metering</span>
                <span className="rail-cell">Model gateway</span>
                <span className="rail-cell">MCP tools</span>
              </div>
            </div>
            <p className="prose" style={{ marginTop: 'var(--s-6)' }}>
              Apps built by other people run on the same rail ours do. Self-hostable, or hosted in Unicorn Cloud. Each listing states its own license rather than inheriting a blanket claim.
            </p>
          </div>
        </section>

        <section className="section-block" id="crew" aria-labelledby="crew-title">
          <div className="shell railed">
            <span className="rail-num">05</span>
            <h2 className="section-title" id="crew-title">The I Have A Business<br />To Run Crew</h2>
            <p className="lede">The product is the handoff. Meetings become decisions. Decisions become assigned work. Customer work stays connected. Completed work becomes a draft invoice and an auditable ledger entry.</p>
            <div className="crew-register">
              {CREW.map((actor) => (
                <article
                  className="crew-member"
                  key={actor.name}
                  style={actor.plate ? { '--b': actor.color, '--plate': actor.plate } : { '--b': actor.color }}
                >
                  <Plate src={actor.mascot} alt={actor.alt} size={128} />
                  <h3 className="crew-name">{actor.name}</h3>
                  <span className={`pill pill-${accessClass(actor.state)}`}>{actor.state}</span>
                  <p className="crew-blurb">{actor.blurb}</p>
                </article>
              ))}
            </div>
            <p className="prose" style={{ marginTop: 'var(--s-8)' }}>{CREW_NOTE}</p>
          </div>
        </section>

        <section className="section-block" id="suite" aria-labelledby="suite-title">
          <div className="shell railed">
            <span className="rail-num">06</span>
            <p className="eyebrow">The bundle</p>
            <h2 className="section-title" id="suite-title">{SUITE.name}</h2>
            <p className="lede">{SUITE.tagline}</p>
            <p style={{ marginTop: 'var(--s-5)' }}><span className="pill pill-development">{SUITE.access}</span></p>
            <div className="rail-cells" style={{ marginTop: 'var(--s-6)' }}>
              {SUITE.includes.map((name) => <span className="rail-cell" key={name}>{name}</span>)}
            </div>
            <p style={{ marginTop: 'var(--s-6)' }}>
              <a className="btn btn-secondary" href={SUITE.cta.href}>{SUITE.cta.label}</a>
            </p>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="shell footer-grid">
          <div className="footer-lockup">
            {/* The ONE permitted use of the brand gradient, sitewide. */}
            <span className="footer-sigil" aria-hidden="true">
              <img src="/logos/uc-mark-colonel.webp" alt="" width="18" height="18" />
            </span>
            <span>Built by Magic Unicorn in Charleston, South Carolina.</span>
          </div>
          <nav className="footer-plinth" aria-label="Audiences">
            <a className="aud-buy" href="#catalog">Buy an AI employee</a>
            <a className="aud-publish" href="https://magicunicorn.dev/book/?product=marketplace-publisher">Publish your own</a>
            <a className="aud-host" href="/marketplace/self-host">Host the whole platform</a>
          </nav>
          <nav className="footer-plinth" aria-label="More">
            <a href="https://magicunicorn.dev/log">Build log</a>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
