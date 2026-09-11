# SyMoNeuRaL Live — the OBS settings, and why each one is the way it is

The video on `/livestack/live` is OBS's **Recording** output, written as HLS straight into
`backend/output/live/`. There is no re-encode, no second recording, no media server and no
RTMP hop: the `.m3u8` and its `.ts` segments **are** both surfaces at once. While OBS is
writing, the playlist is the live stream. When OBS stops cleanly, ffmpeg appends
`#EXT-X-ENDLIST` and the same files become the VOD. One output, two surfaces, nothing copied.

His **Streaming** output is untouched, so YouTube keeps working exactly as it does now. Read
*[Switching to Advanced changes your streaming settings too](#switching-to-advanced-changes-your-streaming-settings-too)*
before touching anything, because that is the one step that can degrade the YouTube feed.

**No router port needs opening.** Port 28001 is never proxied and never reachable from
outside this box. `api.py` is the obs-websocket *client*: it holds the password, connects
outward to loopback, and republishes a handful of readings. See `obs.py`'s docstring for why
proxying 28001 to 443 would instead publish the stream-control credential to every visitor.

---

## The settings

**Settings → Output → Output Mode: `Advanced` → Recording tab.**

| Field | Set it to | Why this exact value |
|---|---|---|
| Recording Type | `Custom Output (FFmpeg)` | The only recording type that exposes a container choice. `Standard` cannot write HLS. |
| FFmpeg Output Type | `Output to File` | Not `Output to URL` — there is no media server, and there does not need to be. |
| File path or URL | `/home/google/Symoneural/backend/output/live` | Must be this directory. `hls.py:OUTPUT_DIR` reads it and nothing else. |
| Container Format | `hls` | Type it in; the field is editable. OBS's bundled libavformat carries the muxer (`Apple HTTP Live Streaming`). |
| **Muxer Settings (if any)** | **`hls_playlist_type=event hls_time=2`** | **Load-bearing. Without it your VOD is the last 10 seconds of the stream.** See below. |
| Video Encoder | `h264_nvenc` | H.264 in MPEG-TS is the one combination every browser decodes. |
| Video Encoder Settings | `b=6000k` | Lower than his YouTube bitrate on purpose — see *Bitrate*. |
| **Keyframe interval (frames)** | **`120`** | **Frames, not seconds.** At 60 fps that is 2 s, matching `hls_time=2`. |
| Audio Encoder | `aac` | `Default Encoder` guesses. Do not make it guess. |
| Audio Bitrate | `160` | What his profile already uses. |
| **Filename Formatting** | **`%CCYY-%MM-%DD_%hh-%mm-%ss`** | **Underscore, not space.** His profile currently has a space. See below. |

Field names are quoted from OBS's own locale, not from memory:
`/var/lib/flatpak/app/com.obsproject.Studio/current/active/files/share/obs/obs-studio/locale/en-US.ini`
lines 1147 (`Custom Output (FFmpeg)`), 1149 (`Filename Formatting`), 1158 (`Container
Format`), 1170 (`Muxer Settings (if any)`) and 1171 (`Keyframe interval (frames)`).

OBS itself warns on this screen that *"Custom Output (FFmpeg) is provided with no
safeguards"* (`en-US.ini:1151`). That is accurate and is the reason this file is this long.

---

## The three settings that fail silently

Each of these produces a recording that looks completely fine in OBS, writes files, and
breaks the site. None of them logs anything. Each was measured here rather than recalled.

### 1. `hls_playlist_type=event` — without it the VOD is ~10 seconds long

ffmpeg's hls muxer defaults to a **rolling** playlist: `hls_list_size` is `5`, so the
`.m3u8` only ever *lists* the newest five segments, however many are on disk. Segments are
not deleted (`hls_delete_threshold` leaves them), so the disk fills up correctly and the
playlist still describes ten seconds of video. When OBS stops, `#EXT-X-ENDLIST` is appended
to that truncated playlist — and that is your VOD. A two-hour stream would archive as the
last ten seconds of itself, with every file present and nothing to read in any log.

Measured, 20 s of test video at `hls_time=2`:

```
default             EXTINF in playlist: 5    segments on disk: 10
hls_playlist_type=event  EXTINF in playlist: 10   segments on disk: 10
```

`event` writes `#EXT-X-PLAYLIST-TYPE:EVENT`, forces the list size to zero so the playlist
only ever grows, and **still appends `#EXT-X-ENDLIST` on a clean stop** — which is the tag
`hls.py` reads to decide a session is finished rather than live. Both halves matter: `vod`
(the other accepted value) would give a complete playlist but is for a file that is already
finished, and is not what a growing recording is.

**To check it on your own recording** — record for a minute, stop, then:

```bash
cd backend/output/live
grep -c '#EXTINF' *.m3u8          # entries the playlist lists
ls *.ts | wc -l                   # segments actually written
grep -c 'EXT-X-ENDLIST' *.m3u8    # 1 after a clean stop, 0 while live
```

The first two numbers must match. If the first is `5`, the muxer settings did not take.

### 2. Filename Formatting must not contain a space

His profile currently reads `FilenameFormatting=%CCYY-%MM-%DD %hh-%mm-%ss`, and **every
format OBS offers in its own dropdown contains a space** (`en-US.ini:1190`) — so this is not
a default to leave alone, it is one to type over.

The space survives all the way into the playlist. Measured:

```
file written:   2026-08-21 14-30-00.m3u8
URI inside it:  2026-08-21 14-30-000.ts
```

`hls.py:SAFE_NAME` refuses it, deliberately: a name with a space cannot be handed to
`/api/live/hls/{name}` without an escaping question, and the safe answer to an escaping
question in a path is to refuse. What the surface then does is report it rather than hide it
— `/api/live/state` lists the session under `unservable` with a sentence saying why, and the
page shows that sentence. A recording that exists but cannot be served is a fact a visitor
should see, not one to silently skip.

So a space costs you the recording, but it costs it *loudly*. Use the underscore.

### 3. Keyframe interval is in **frames**

The field is labelled `Keyframe interval (frames)` (`en-US.ini:1171`) and OBS's Simple-mode
equivalent is in seconds, which is where the mistake comes from. At 60 fps:

| you want | type |
|---|---|
| 2 s | `120` |

Get this wrong and segments cannot be cut at the length you asked for, because a segment
boundary has to be a keyframe. Leave it at `250` (the ffmpeg default) and `hls_time=2`
becomes a request ffmpeg cannot honour: you get ~4.2 s segments and roughly double the
latency to the live edge. This is the same defect `site/streamer.html:2022` documents from
the other direction — a provider with a 10-second GOP made `hls_time=2` meaningless and cost
31 seconds before first video.

---

## Bitrate, and why it is lower than his YouTube one

His profile streams at `VBitrate=18000` (18 Mbit/s) at 1920x1080/60. That is right for
YouTube, which transcodes it into a ladder. It is wrong for this site, which serves exactly
what it is given, to whoever asks, over his home upstream — an 18 Mbit/s HLS stream is
unwatchable for most visitors and there is no ladder to fall back to.

`b=6000k` is the recommendation. The cost either way, **projected arithmetic, not measured**:

| video bitrate | per hour on disk | per visitor |
|---|---|---|
| 6000 kbit/s + 160 audio | ≈ 2.8 GB | ≈ 0.77 MB/s |
| 18000 kbit/s + 160 audio | ≈ 8.2 GB | ≈ 2.3 MB/s |

Nothing in this app deletes a recording, ever, so that per-hour figure accumulates. That is
a deliberate choice — the app can be wrong about which session matters, and `rm` is not
reversible — but it does mean the number above is the number to watch. `/api/live/usage`
reports the total so you never have to guess, and `du -sh backend/output/live` is the same
answer from the other side.

---

## Switching to Advanced changes your streaming settings too

His profile is `Mode=Simple` today. Simple mode uses one set of controls for both outputs;
Advanced mode has a separate **Streaming** tab, and its fields have never been configured on
this profile (`RecType=Standard`, `FFExtension=mp4` — untouched defaults).

So after switching to Advanced, **open the Streaming tab and mirror what Simple was doing**,
or the YouTube feed changes underneath him without any warning:

| Streaming tab | set to | (Simple mode's value today) |
|---|---|---|
| Video Encoder | NVIDIA NVENC H.264 | `StreamEncoder=nvenc` |
| Bitrate | 18000 Kbps | `VBitrate=18000` |
| Audio Bitrate | 160 | `ABitrate=160` |

Read from `~/.var/app/com.obsproject.Studio/config/obs-studio/basic/profiles/ITWORKS/basic.ini`
on 2026-08-21. If that profile has changed since, re-read it — do not trust this table.

---

## NVENC and the GPU governor

`scripts/gpu-governor.sh` cannot see this and cannot evict it. OBS holds its own NVENC
session for as long as it is encoding, outside the lock, so the governor's 1500 MiB drain
floor does not account for it and a `train` or `studio` tenant will find that much less card
than the governor believes is free.

**This is a statement about what the governor does not know, not a measurement of the
cost.** Nobody has yet measured what an NVENC session at 1080p60 holds on this card while a
GPU tenant is running. Until somebody does, do not claim on the site or anywhere else that
streaming coexists with a fine-tune — measure it first and write the number down here.

---

## Configuring the bridge

Only the telemetry line — scene, fps, dropped frames — needs any of this. **The video needs
none of it**; `hls.py` reads a directory and holds no credential. A blank env file leaves the
page working with that line reading "not configured".

```bash
cd backend/apps/live
cp symoneural-live.env.example symoneural-live.env
chmod 600 symoneural-live.env
```

Then put the obs-websocket password in it. **Rotate it first**: that password was displayed
in a screenshot, in plain text beside a QR code encoding the same value, and a credential
that has been displayed is spent. OBS → Tools → WebSocket Server Settings → **Generate
Password** → Apply, and paste the new one. It costs one click.

`symoneural-live.env` can never be committed: `.gitignore` carries `*.env` with
`!*.env.example`, and `scripts/lib/archive-guard.sh` refuses to build any archive containing
a real `.env` **or** any file assigning `SYMONEURAL_OBS_PASSWORD` a value — the second rule
is there for `live.env.old` and the copy pasted into a scratch note, which the first rule
does not catch.

### Proving the handshake works

The v5 auth is `base64(sha256(base64(sha256(password + salt)) + challenge))`, and getting the
two rounds the wrong way round produces a perfectly well-formed 44-character string that OBS
rejects with an unhelpful close code. No offline test can tell those apart, so there is a
real one:

```bash
cd backend && python3 -m apps.live.verify_bridge
```

It reads the password out of OBS's own config, uses it for one handshake, and never prints
it. **Measured 2026-08-21, PASS** — obs-websocket 5.7.4, rpc 1, auth required, all four
probes answered, against OBS 32.2.2 on the Flatpak runtime.

---

## `backend/output/live/` is a publish surface

Anything OBS writes there is listed by `/api/live/vods` and served by `/api/live/hls/{name}`
**the moment a segment lands**. It is not a scratch recording directory and must not be used
as one: point OBS somewhere else for a recording that is not meant to be public, or it is
public.

It is served by the API rather than copied into `site/`, and that is not an arbitrary choice.
`site/` is a staging directory; the web server serves `/var/www/symoneural`. A file written
into `site/` 404s for every visitor until somebody runs `deploy.sh` — which is exactly how 19
unreferenced renders ended up in the public webroot and how every image generated on the live
site used to 404. Renders were moved to `backend/output/` and `/api/gen/<name>` for this
reason; live segments use the same fix from the start. A live stream that only appears after
a deploy is not a live stream.

---

## What the page does with it

`site/live.js` drives playback through **hls.js**, already vendored at `site/hls.js` (v1.7.0,
Apache-2.0, licence at `site/hls-LICENSE.txt`, credited on `site/credits.html:208`) for
`streamer.html`. It is not optional: Chrome and Firefox will not play HLS natively.

The trap, measured in this repo and written up at `site/streamer.html:1989`, is that Chrome's
`video.canPlayType('application/vnd.apple.mpegurl')` returns **`'maybe'`** — a truthy string
— so the obvious `if (canPlayType(...)) { native } else { hls.js }` takes the native branch
on every Chrome visit and plays nothing at all. **Try `Hls.isSupported()` first and fall back
to native only where hls.js will not run**, which is Safari. That ordering is a bug fix, not
a preference, and it already cost this repo one round.

<!-- generated: do not edit below -->

## Operations — 9

|  | path | what it does |
|---|---|---|
| GET | `/api/live/hls/{name}` | A playlist or one of its segments |
| GET | `/api/live/now` | The playlist being written right now |
| GET | `/api/live/state` | Is he live, what is on disk, and what OBS last reported |
| GET | `/api/live/usage` | What the recordings cost on disk |
| GET | `/api/live/vods` | Everything watchable after the fact, newest first |
| GET | `/live-stack/coder` | SyMoNeuRaL Coder: the browser surface. |
| GET | `/live-stack/live` | SyMoNeuRaL Live, at the address he asked every app to be at. |
| GET | `/livestack/coder` | SyMoNeuRaL Coder: the browser surface. |
| GET | `/livestack/live` | SyMoNeuRaL Live, at the address he asked every app to be at. |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `hls.py` | The playlist directory: what OBS wrote, and which of it is live. |
| `obs.py` | The obs-websocket v5 bridge: this process is the client, and the password never leaves it. |
| `verify_bridge.py` | Prove the obs-websocket handshake works, without anybody typing or reading the password. |

## Documents

- [`symoneural-live-scope.md`](docs/symoneural-live-scope.md)
- [`symoneural-live-stack.md`](docs/symoneural-live-stack.md)

<!-- end generated -->
