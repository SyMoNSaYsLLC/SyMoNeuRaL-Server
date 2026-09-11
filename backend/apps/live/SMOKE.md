# apps/live — smoke record

Written only after a real OBS stream was watched playing in a browser, per #96's own note.
Everything below is **measured on this machine**; the two things that were *not* measured are
named as such at the bottom, because #96 also says not to publish a figure for them until they
have been.

    date        2026-08-21
    commit      75b5293
    OBS         com.obsproject.Studio flatpak, Advanced -> Recording -> Custom Output (FFmpeg)
    encoder     h264_nvenc   (libx264 was the only entry in the dropdown until
                              "Show all codecs (even if potentially incompatible)" was ticked
                              -- libavformat's hls muxer advertises no codec list, so OBS
                              offered the container's DEFAULT codec and nothing else)
    driver      610.57.04, NVENC 13.1, Blackwell, [h264] codec_supported=1
                (obs-nvenc-test, run INSIDE the flatpak sandbox -- the host having
                 libnvidia-encode.so.1 proves nothing about what OBS can reach)

## The assertion this file exists for

A `<video>` element with an HLS URL behind it satisfies `exists`, `grep` and every DOM check
anybody would think to write while playing nothing at all. That is #94's shape: eighteen green
checks and a surface that was dead on arrival. So the record is what a real run produced.

Against the running service at `http://127.0.0.1:8800/livestack/live`, system Chrome:

    readyState        4        (HAVE_ENOUGH_DATA)
    videoWidth/Height 1920x1080
    currentTime       advanced 9.01 s over a 9 s wall-clock wait, paused=false
    console errors    0

**And a second segment appeared while the first was still playing** — that is the half a
finished recording cannot demonstrate, and the reason this file waited for a live one:

    segments  36 -> 40        seconds  72 -> 80        state stayed "live"

## The playlist, and the three settings that fail silently

All three took. Read off the real playlist rather than off the settings dialog, because the
dialog is what you asked for and the playlist is what you got:

    #EXT-X-PLAYLIST-TYPE:EVENT      hls_playlist_type=event took -- without it hls_list_size
                                    defaults to 5 and the VOD is the last ~10 s of the stream
    #EXT-X-TARGETDURATION:2         hls_time=2 took
    #EXTINF:2.000000 (every one)    keyframe interval 120 FRAMES at 60 fps = 2 s, so every
                                    segment boundary lands on a keyframe. Ragged EXTINF values
                                    are the symptom of getting this one wrong.
    EXTINF count == .ts on disk     104 == 104. If the first number is 5, the muxer settings
                                    did not take at all.
    filename                        2026-08-21_13-13-10.m3u8 -- underscore, no space, so
                                    hls.py's SAFE_NAME accepts it and it is servable:true.
                                    "Generate File Name without Space" is what did it; the
                                    profile's FilenameFormatting still contains a space.

## Bitrate and disk, measured rather than assumed

    configured    6000 kbps ceiling (the Video Bitrate spinner; NVENC ran VBR under it)
    measured      58,195,454 bytes over 208.0 s  =  2.24 Mbit/s average
    disk          ~1.0 GB/hour at that rate

**The measured rate is a third of the ceiling** and this is content-dependent, not a property
of the settings: the scene was a mostly-static desktop, and individual segments in the same
run range from 153 kB to 960 kB. Do not quote ~1.0 GB/hour as the number for a moving scene,
and do not quote the ceiling arithmetic (2.8 GB/hour) as a measurement. Nothing in `apps/live`
ever deletes a recording.

## NVENC beside the governor

    obs, resident       372-378 MiB  (nvidia-smi --query-compute-apps, during the stream)
    encoder utilisation 4-7 %
    whole card          1685-1817 MiB of 16,303 used, desktop included

`scripts/gpu-governor.sh` read `lock free` throughout. That is the documented blind spot, now
observed rather than predicted: OBS holds its own NVENC session, the governor cannot see it and
cannot evict it.

**Correction, 2026-08-21.** The sentence above ended *"and does not count those ~375 MiB against
its 1500 MiB drain floor"*, and that half was wrong when it was written. The floor was compared
against `--query-gpu=memory.used`, which counts **every** context on the device including
graphics — so those MiB were counted, and were part of what took `/api/chat` down for an
afternoon (R-171, `.claude/HANDOVER.md` §0a-sexies). It is true now, and structurally rather
than by luck: `drain` sums `--query-compute-apps`, and the process table on this box shows OBS
as a `G` context at 49 MiB with no row in that query at all. The two readings in this record are
therefore of different things and both are kept: 372–378 MiB was read from the full process
table during the stream, and 49 MiB is what a compute-only query would have seen. Even taking
the larger figure, the floor is 1024 MiB and clears it.

## NOT measured — do not publish a figure for either

* **NVENC alongside a GPU tenant.** No chat, image or training tenant was resident during this
  run, so this record says nothing about whether an NVENC session at 1080p60 coexists with one.
  `apps/live/README.md` asks for that reading; it is still owed.
* **Glass-to-glass latency.** Nothing in the scene carried a clock, so no honest number exists.
  A 2 s segment and a 3-segment player buffer bound it from below at ~6 s and that is
  arithmetic, not a measurement.
