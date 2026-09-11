#!/bin/bash
# What it actually costs to make an un-playable IPTV channel play. Measured on this box.
#
# Three separate questions, because they have wildly different answers and the audit has been
# conflating them:
#
#   A. The audio-only fix. If the defect is AC-3/E-AC-3 (Chrome decodes neither) the video is
#      already fine and the fix is `-c:v copy -c:a aac`. No GPU, no re-encode of the picture.
#   B. Video transcode of a real IPTV stream, full GPU path (cuvid decode -> NVENC encode).
#   C. Video transcode of synthetic 1080p25, which is what a worst-case HEVC channel looks like.
#      testsrc2 is high-entropy and near-worst-case for rate control -- this is a FLOOR on
#      throughput, not a prediction for any particular channel. Labelled as such.
#
# Bounded on purpose: runs under a governor lease and finishes in ~2 minutes.
set -u
cd "$(dirname "$0")" || exit 1
W=nvbench; rm -rf $W; mkdir -p $W

vram() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; }

# ---------------------------------------------------------------- real source
# Consecutive segments captured from a live channel with tools/audit/probe_tuner_stream.sh and left
# beside this script, concatenated back into one continuous stream. Real broadcast bytes, not a
# test pattern -- which matters, because a synthetic source flatters a rate-control decision that
# real video does not.
#
# Deliberately not committed: they are somebody's IPTV subscription, and a repo is not where that
# belongs. Absent, this reports the synthetic cases only and says so rather than quietly measuring
# a zero-byte file, which is what it did before this guard and which produced a "0 bytes, s" line
# that looked like a result.
REAL_S=0
if ls seg-*.ts >/dev/null 2>&1; then
  cat $(ls seg-*.ts | sort) > $W/real.ts 2>/dev/null
  REAL_S=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $W/real.ts 2>/dev/null | cut -d. -f1)
  REAL_S=${REAL_S:-0}
fi
if [ "${REAL_S:-0}" -gt 0 ] 2>/dev/null; then
  echo "=== real source: $(stat -c%s $W/real.ts) bytes, ${REAL_S}s ==="
  ffprobe -v error -show_entries stream=codec_type,codec_name,profile,width,height,channels \
          -of default=noprint_wrappers=1 $W/real.ts | paste -sd' ' -
else
  REAL_S=0
  echo "=== real source: NONE ==="
  echo "no seg-*.ts beside this script, so the real-IPTV rows are SKIPPED, not measured."
  echo "capture some with tools/audit/probe_tuner_stream.sh while a channel is open, and re-run."
fi

# ---------------------------------------------------------------- synthetic HEVC
SYN_S=60
echo
echo "=== synthetic source: ${SYN_S}s 1080p25 HEVC + AC-3 (what a browser refuses outright) ==="
ffmpeg -v error -y -f lavfi -i "testsrc2=size=1920x1080:rate=25:duration=$SYN_S" \
       -f lavfi -i "sine=frequency=440:duration=$SYN_S" \
       -c:v hevc_nvenc -preset p4 -b:v 6M -c:a ac3 -b:a 192k \
       -f mpegts $W/syn.ts 2>&1 | tail -3
echo "synthetic: $(stat -c%s $W/syn.ts) bytes"

# ---------------------------------------------------------------- one run
# Peak VRAM is sampled at 5 Hz from bash. On the shortest runs that is only a few dozen samples,
# so treat the VRAM column as approximate -- it is a magnitude check ("hundreds of MB, not GB"),
# which is the only precision the MAX_SESSIONS=2 decision needs.
#
# HOW THE VRAM COLUMN LIES, AND WHEN. It is a delta of *whole-card* memory, not this process's
# usage, so any other tenant allocating during a run is billed to whatever row is executing. A
# second run of this script taken while ~8 GB was already resident reported `all-CPU libx264
# veryfast ... VRAM +6576 MiB`, which is impossible -- libx264 does not touch the card at all.
# That row is the canary: **if the pure-CPU case reports more than a few MiB, the whole run is
# contaminated and every number in it should be thrown away.** The governor lease does not
# prevent this on its own, because a surface can be resident without holding the lock.
#
# Take these on an idle card. `nvidia-smi` should read about 1 GiB before you start.
run() {   # run <label> <duration_s> <input> "<input opts>" "<output opts>"
  # A zero duration means the source is absent. Skip loudly: a silent skip in a benchmark reads
  # as a case that passed.
  if [ "${2:-0}" = "0" ]; then printf '%-38s SKIPPED (no real source)\n' "$1"; return; fi
  # Input options and output options are separate arguments because ffmpeg is positional:
  # everything before -i binds to the input, everything after binds to the output. Passing one
  # flat list put -b:v on the input and every run failed with "cannot be applied to input url".
  local label="$1" dur="$2" input="$3" inopts="$4" outopts="$5"
  local base peak pid t0 t1 el x
  base=$(vram); peak=$base
  t0=$(date +%s.%N)
  ffmpeg -v error -y $inopts -i "$input" $outopts -f null - 2>$W/err.txt &
  pid=$!
  while kill -0 $pid 2>/dev/null; do
    local u; u=$(vram); [ "$u" -gt "$peak" ] && peak=$u
    sleep 0.2
  done
  wait $pid; local rc=$?
  t1=$(date +%s.%N)
  el=$(echo "$t1 - $t0" | bc)
  if [ $rc -ne 0 ]; then
    printf '%-38s FAILED: %s\n' "$label" "$(head -1 $W/err.txt)"
    return
  fi
  x=$(echo "scale=1; $dur / $el" | bc)
  printf '%-38s %6.2fs  %6sx realtime   VRAM +%s MiB\n' "$label" "$el" "$x" "$((peak - base))"
}

echo
echo "=== A. audio-only fix (video untouched) -- the repair if the defect is AC-3 ==="
run "real: -c:v copy -c:a aac  (CPU)"      "$REAL_S" $W/real.ts "" "-c:v copy -c:a aac"
run "syn:  -c:v copy -c:a aac  (CPU)"      "$SYN_S"  $W/syn.ts  "" "-c:v copy -c:a aac"

echo
echo "=== B. real IPTV video transcode ==="
run "real: h264_cuvid -> h264_nvenc (GPU)" "$REAL_S" $W/real.ts \
    "-hwaccel cuda -hwaccel_output_format cuda -c:v h264_cuvid" "-c:v h264_nvenc -preset p4 -b:v 6M -c:a aac"
run "real: CPU decode -> h264_nvenc"       "$REAL_S" $W/real.ts \
    "" "-c:v h264_nvenc -preset p4 -b:v 6M -c:a aac"
run "real: all-CPU  libx264 veryfast"      "$REAL_S" $W/real.ts \
    "" "-c:v libx264 -preset veryfast -b:v 6M -c:a aac"

echo
echo "=== C. synthetic HEVC -> H.264, worst case (floor, not a prediction) ==="
run "syn:  hevc_cuvid -> h264_nvenc (GPU)" "$SYN_S" $W/syn.ts \
    "-hwaccel cuda -hwaccel_output_format cuda -c:v hevc_cuvid" "-c:v h264_nvenc -preset p4 -b:v 6M -c:a aac"
run "syn:  hevc_cuvid -> h264_nvenc, audio copy" "$SYN_S" $W/syn.ts \
    "-hwaccel cuda -hwaccel_output_format cuda -c:v hevc_cuvid" "-c:v h264_nvenc -preset p4 -b:v 6M -c:a copy"
run "syn:  all-CPU  libx264 veryfast"      "$SYN_S" $W/syn.ts \
    "" "-c:v libx264 -preset veryfast -b:v 6M -c:a aac"

echo
echo "=== D. concurrency: does MAX_SESSIONS=2 fit, and where is the ceiling? ==="
for n in 2 4; do
  base=$(vram); peak=$base
  t0=$(date +%s.%N)
  pids=""
  for i in $(seq $n); do
    ffmpeg -v error -y -hwaccel cuda -hwaccel_output_format cuda -c:v hevc_cuvid \
           -i $W/syn.ts -c:v h264_nvenc -preset p4 -b:v 6M -c:a aac -f null - 2>/dev/null &
    pids="$pids $!"
  done
  # Poll the pids we actually started, rather than `jobs -rp`, which also sees anything else
  # this shell left running.
  while :; do
    local_alive=0
    for p in $pids; do kill -0 "$p" 2>/dev/null && local_alive=1; done
    [ $local_alive -eq 0 ] && break
    u=$(vram); [ "$u" -gt "$peak" ] && peak=$u
    sleep 0.2
  done
  for p in $pids; do wait "$p" 2>/dev/null; done
  t1=$(date +%s.%N); el=$(echo "$t1 - $t0" | bc)
  printf '%2d concurrent HEVC->H264  %6.2fs  aggregate %sx realtime  VRAM +%s MiB (~%s each)\n' \
    "$n" "$el" "$(echo "scale=1; ($SYN_S * $n) / $el" | bc)" "$((peak - base))" "$(( (peak - base) / n ))"
done

echo
echo "=== encoder/decoder engine load during a GPU transcode (are they really separate ASICs?) ==="
ffmpeg -v error -y -hwaccel cuda -hwaccel_output_format cuda -c:v hevc_cuvid -i $W/syn.ts \
       -c:v h264_nvenc -preset p4 -b:v 6M -c:a aac -f null - 2>/dev/null &
BP=$!
sleep 1
for i in 1 2 3 4 5; do
  nvidia-smi --query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used \
             --format=csv,noheader
  sleep 0.4
done
wait $BP 2>/dev/null
rm -rf $W
