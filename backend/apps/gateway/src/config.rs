//! Everything that differs between this box and any other, read from the environment once
//! at startup. There are no compiled-in hostnames and no config file, because the systemd
//! unit is already the place this project puts environment for a service.

use std::net::SocketAddr;
use std::path::PathBuf;

/// Where the gateway listens, and what it forwards to.
#[derive(Debug, Clone)]
pub struct Config {
    pub bind: SocketAddr,

    /// The FastAPI control plane. `backend/api.py`, on 127.0.0.1:8800 under
    /// `symoneural-api.service`.
    pub api_upstream: String,

    /// Where `/v1/*` goes.
    ///
    /// **This defaults to the FastAPI control plane, not to llama.cpp**, and that default is
    /// the important part of this file. On this machine `llama-server` is not a service: it
    /// is a *child process* that `backend/api.py` spawns per job while holding the mutex in
    /// `scripts/gpu-governor.sh` (see `backend/api.py:113`). Nothing listens on :8080 or
    /// :9001 between jobs. Pointing this at an engine port would therefore
    ///
    ///   1. connect to nothing most of the time, and
    ///   2. when it *did* connect, use the GPU without holding the governor lock — which
    ///      `.claude/CLAUDE.md` forbids outright ("Everything touching the GPU goes through
    ///      `scripts/gpu-governor.sh`"), and which would contend with a QLoRA run for VRAM
    ///      that cannot be shared.
    ///
    /// Set `SYMON_ENGINE_UPSTREAM=http://127.0.0.1:8080` only once something owns the lock
    /// on the engine's behalf.
    pub engine_upstream: String,

    /// Compiled Go validator. Absent is a supported state; see `middleware.rs`.
    pub wasm_path: PathBuf,

    /// Refuse a chat payload above this many estimated tokens.
    pub max_tokens: u64,

    /// Upstream request timeout. Generous, because a cold model load is minutes.
    pub upstream_timeout_secs: u64,

    /// The most a `/v1/chat/completions` body may be, in bytes, before it is refused with 413.
    ///
    /// This route is the one place the gateway must hold the whole body in memory, because it
    /// validates before forwarding. Every other route streams straight through and has no cap
    /// at all — deliberately: `backend/apps/voice/routes.py:43` records that every size cap on
    /// uploads was removed and that the route reads in 64 KiB chunks precisely so a long
    /// recording is never resident. A blanket body limit on this process would quietly undo
    /// that. 8 MiB is roughly 80× the 100,000-character prompt ceiling in `api.py:156`, so it
    /// bounds memory without being reachable by a legitimate request.
    pub max_chat_body_bytes: usize,

    /// Whether to believe an inbound `X-Forwarded-For`.
    ///
    /// `api.py:505` keys its rate limiter on the *first* entry of that header, so whoever
    /// writes it decides who gets throttled. Two deployments, two right answers:
    ///
    ///   * **Caddy in front** (`true`): the first entry is the real client, written by Caddy.
    ///     Preserve it and append this hop.
    ///   * **This process is the front door** (`false`, the default): there is no trusted
    ///     writer upstream, so any inbound value is client-supplied and a client that sends
    ///     its own `X-Forwarded-For: <anything>` gets a fresh rate-limit bucket per request.
    ///     Overwrite it with the peer address.
    ///
    /// The default is the fail-closed one. Getting it wrong in the `false` direction puts
    /// every client in one shared bucket, which throttles too much; getting it wrong in the
    /// `true` direction removes the limiter entirely for anyone who reads this file.
    pub trust_forwarded: bool,
}

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        let bind: SocketAddr = env_or("SYMON_GATEWAY_BIND", "127.0.0.1:8000").parse()?;

        Ok(Self {
            bind,
            api_upstream: trim_slash(&env_or("SYMON_API_UPSTREAM", "http://127.0.0.1:8800")),
            engine_upstream: trim_slash(&env_or(
                "SYMON_ENGINE_UPSTREAM",
                "http://127.0.0.1:8800",
            )),
            wasm_path: PathBuf::from(env_or(
                "SYMON_WASM_LIMITER",
                "ops/middleware/limiter.wasm",
            )),
            max_tokens: env_or("SYMON_MAX_TOKENS", "100000").parse().unwrap_or(100_000),
            upstream_timeout_secs: env_or("SYMON_UPSTREAM_TIMEOUT", "900")
                .parse()
                .unwrap_or(900),
            max_chat_body_bytes: env_or("SYMON_MAX_CHAT_BODY", "8388608")
                .parse()
                .unwrap_or(8 * 1024 * 1024),
            trust_forwarded: matches!(env_or("SYMON_TRUST_FORWARDED", "0").as_str(), "1"),
        })
    }
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

/// A trailing slash on the upstream would produce `http://host:8800//api/status`. Some
/// servers normalise that and some 404 on it; not relying on which is cheaper than finding out.
fn trim_slash(s: &str) -> String {
    s.trim_end_matches('/').to_string()
}
