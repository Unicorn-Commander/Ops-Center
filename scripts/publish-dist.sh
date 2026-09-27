set -euo pipefail
cd /home/muut/Production/UC-Cloud/services/ops-center
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BK=/home/muut/backups/ops-center-public-$STAMP
mkdir -p "$BK"
cp -a public/index.html "$BK/" 2>/dev/null || true
cp -a public/assets      "$BK/" 2>/dev/null || true
cp -a public/sw.js       "$BK/" 2>/dev/null || true
echo "backup: $BK"
# copy build output over, WITHOUT deleting anything that isn't in dist
cp -a dist/index.html public/index.html
cp -a dist/assets/.   public/assets/
[ -f dist/sw.js ] && cp -a dist/sw.js public/sw.js
[ -f dist/workbox-28240d0c.js ] && cp -a dist/workbox-*.js public/ 2>/dev/null || true
# logos must survive (they are ours, not vite's)
ls public/logos/tile-*.png | wc -l | xargs echo "tile logos present:"
echo "new entry bundle:"
grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' public/index.html | head -2
