#!/bin/bash
# One shot: read the live session, pull its playlist, and immediately pull the segments it
# advertises. Back to back on purpose -- a 2 s segment in a 6-segment window ages out in ~12 s,
# so anything slower than this measures the rolling window rather than the bug.
B=http://127.0.0.1:8800
cd "$(dirname "$0")" || exit 1

SID=$(curl -s $B/api/tuner/state | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["sessions"][0]["id"] if d["sessions"] else "")')
if [ -z "$SID" ]; then echo "no live session -- open a channel on the page and re-run"; exit 2; fi
echo "session $SID"
curl -s $B/api/tuner/state | python3 -c 'import sys,json; d=json.load(sys.stdin); s=d["sessions"][0]; print("  vcodec=%s state=%s segments=%s bytes_in=%s age=%.0fs" % (s["vcodec"], s["state"], s["segments"], s["bytes_in"], s["age_s"]))'

curl -s -o pl.m3u8 -w "playlist: %{http_code} %{size_download}b\n" "$B/api/tuner/stream/$SID/live.m3u8"
SEGS=$(grep -o 's[0-9]*\.ts' pl.m3u8)
echo "advertised: $(echo $SEGS | tr '\n' ' ')"

# Every advertised segment, newest last. A playlist that advertises what the server will not
# serve is the failure being tested for.
OK=0; BAD=0; FIRSTGOOD=""
for s in $SEGS; do
  code=$(curl -s -o "seg-$s" -w '%{http_code}' "$B/api/tuner/stream/$SID/$s")
  size=$(stat -c%s "seg-$s" 2>/dev/null || echo 0)
  printf '  %-12s %s %8sb\n' "$s" "$code" "$size"
  if [ "$code" = "200" ] && [ "$size" -gt 10000 ]; then OK=$((OK+1)); [ -z "$FIRSTGOOD" ] && FIRSTGOOD="seg-$s"; else BAD=$((BAD+1)); fi
done
echo "served $OK, refused $BAD"

if [ -n "$FIRSTGOOD" ]; then
  echo "--- codecs actually in the segment the browser gets ---"
  ffprobe -v error -show_entries stream=index,codec_type,codec_name,profile,width,height,channels,sample_rate \
    -of default=noprint_wrappers=1 "$FIRSTGOOD"
fi
