#!/usr/bin/env bash
# Re-vendor the fleet-map viewer (Forgejo UnicornCommander/fleet-map) into public/fleet-map/
# and re-apply the Ops-Center patches. Idempotent; fails loudly if an anchor moved upstream.
#
#   scripts/vendor-fleet-map.sh <path-to-fleet-map-checkout>
#
# Copies:  index.html, d3.v7.min.js, vendor/fleet3d.bundle.js (-> fleet3d.bundle.js), assets/agents/*.webp
# Patches (all inside index.html):
#   1. data: <script src="data.js"> -> /api/v1/fleet/map.js (admin session cookie rides on the <script src>)
#   2. "Fleet map unavailable" message when window.FLEET is missing (no data yet / not signed in)
#   3. no-WebGL -> start on the 2D graph instead of a blank 3D pane
#   4. outbound hostname links open in a new tab (the viewer runs inside an iframe)
# The viewer is served by backend/fleet_map_api.py at /api/v1/fleet/viewer/<path>; relative
# references (d3.v7.min.js, fleet3d.bundle.js, assets/agents/*.webp) resolve under that prefix.
set -euo pipefail
SRC="${1:?usage: $0 <path-to-fleet-map-checkout>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DST="$HERE/public/fleet-map"
for f in index.html d3.v7.min.js vendor/fleet3d.bundle.js; do [ -f "$SRC/$f" ] || { echo "missing $SRC/$f" >&2; exit 1; }; done

mkdir -p "$DST/assets/agents"
cp "$SRC/d3.v7.min.js" "$DST/d3.v7.min.js"
cp "$SRC/vendor/fleet3d.bundle.js" "$DST/fleet3d.bundle.js"
if [ -d "$SRC/assets/agents" ]; then cp "$SRC"/assets/agents/*.webp "$DST/assets/agents/"; fi

python3 - "$SRC/index.html" "$DST/index.html" <<'PY'
import sys, re
src, dst = sys.argv[1], sys.argv[2]
h = open(src, encoding="utf-8").read()

def once(old, new, what):
    global h
    n = h.count(old)
    if n != 1:
        sys.exit(f"vendor-fleet-map: anchor for {what} found {n}x (expected 1): {old[:70]!r}")
    h = h.replace(old, new)

# 1+2+3: data source, unavailable message, no-WebGL fallback
once('<script src="d3.v7.min.js"></script><script src="vendor/fleet3d.bundle.js"></script><script src="data.js"></script>',
     '<!-- Ops-Center build (scripts/vendor-fleet-map.sh): data comes from the console API (admin session cookie rides on\n'
     '     the <script src>), not a static data.js. Source: UnicornCommander/fleet-map index.html - re-vendor, do not hand-edit.\n'
     '     Served at /api/v1/fleet/viewer/index.html; sibling files and assets/agents/*.webp resolve relatively. -->\n'
     '<script src="d3.v7.min.js"></script><script src="fleet3d.bundle.js"></script><script src="/api/v1/fleet/map.js"></script>\n'
     '<script>\n'
     'if(!window.FLEET){\n'
     '  const st=window.FLEET_STATUS||{}; const why=window.FLEET_STATUS?"No fleet topology has been ingested on this node yet"+(st.ingest_configured?"":" (ingest token not configured)")+".":"Could not load the topology - sign in to the console as an admin (this page is served by Ops-Center, not a file).";\n'
     '  document.getElementById("app").innerHTML=\'<div style="grid-column:1/-1;display:flex;align-items:center;justify-content:center;height:100vh;padding:24px;text-align:center;color:#8ea0bd;font-size:14px;line-height:1.6"><div><div style="font-size:22px;color:#e6edf7;margin-bottom:8px">Fleet map unavailable</div>\'+why.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))+\'<div style="margin-top:10px;font-size:12px">Collector: bigboy panel-fleet-push.timer &rarr; POST /api/v1/fleet/ingest</div></div></div>\';\n'
     '  throw new Error("fleet-map: no data");\n'
     '}\n'
     '// No WebGL (remote desktops, hardened browsers): the 3D default would be a blank pane - start on the 2D graph instead.\n'
     'try{ const c=document.createElement("canvas"); if(!(c.getContext("webgl2")||c.getContext("webgl"))) localStorage.setItem("fleetmap-view","graph"); }catch(e){ try{localStorage.setItem("fleetmap-view","graph");}catch(_){} }\n'
     '</script>', "script tags")
once('const F=window.FLEET; const LAYERS=F.layers;',
     'const F=window.FLEET; if(!F) throw new Error("fleet-map: no data"); const LAYERS=F.layers;', "F guard")

# 4: outbound hostname links must not navigate the iframe
total = len(re.findall(r'href="https://\$\{esc\(', h))
h, n = re.subn(r'href="https://\$\{esc\(([^)]*)\)\}"(?! target=)', r'href="https://${esc(\1)}" target="_blank" rel="noopener"', h)
if total == 0:
    sys.exit("vendor-fleet-map: no outbound href anchors found (viewer markup changed?)")
open(dst, "w", encoding="utf-8").write(h)
print(f"patched index.html: {len(h)} bytes, outbound links: {total} total, {n} retargeted, {total-n} already had target=")
PY

SHA=$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)
printf 'source: UnicornCommander/fleet-map @ %s\nvendored: %s by scripts/vendor-fleet-map.sh\nfiles: index.html d3.v7.min.js fleet3d.bundle.js assets/agents/*.webp (%s)\n' \
  "$SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(ls "$DST/assets/agents" | wc -l | tr -d ' ')" > "$DST/VENDOR.txt"
cat "$DST/VENDOR.txt"
