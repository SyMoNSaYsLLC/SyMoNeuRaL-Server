//! SyMoNeuRaL Gateway — the front door.
//!
//! ```text
//!   client ──▶ Caddy :443 (TLS, static files) ──▶ symon-gateway :8000 ──▶ FastAPI :8800
//!                                                        │                     │
//!                                                        │                     └─ gpu-governor.sh
//!                                                        └─ limiter.wasm (validate, then forward)
//! ```
//!
//! **What this process does not do.** It terminates no TLS, serves no files off disk, and
//! makes no routing decision — it forwards paths to the process that owns them. That is the
//! rule in `.claude/CLAUDE.md` ("FastAPI does all the routing"), preserved with one more hop
//! in the path.
//!
//! Whether Caddy stays in front of this or is replaced by it is an open question at the time
//! of writing, and the answer changes this file: replacing Caddy means taking on ACME/TLS,
//! static file serving from `/var/www/symoneural`, and — the one that is easy to miss — the
//! WebSocket upgrade on `/api/ws`, which is *why* Apache was dropped for Caddy in the first
//! place. Nothing below assumes either answer.

mod config;
mod error;
mod middleware;
mod models;
mod proxy;
mod router;
mod ws;

use std::sync::Arc;
use std::time::Duration;

use config::Config;
use middleware::Validator;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub http: reqwest::Client,
    pub validator: Arc<Validator>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // JSON on request, so the same log file can carry Python's records too. Plain text
    // otherwise, because a human reading `journalctl` is the common case.
    let filter = tracing_subscriber::EnvFilter::try_from_env("SYMON_LOG")
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info,tower_http=info"));
    if std::env::var("SYMON_LOG_JSON").is_ok() {
        tracing_subscriber::fmt().json().with_env_filter(filter).init();
    } else {
        tracing_subscriber::fmt().with_env_filter(filter).init();
    }

    let cfg = Config::from_env()?;
    let validator = Validator::load(&cfg.wasm_path, cfg.max_tokens)?;

    let http = reqwest::Client::builder()
        // Applies to the whole request including the body. A streamed completion can legitimately
        // run for many minutes behind a cold model load, so this is generous on purpose; the
        // guard that matters is `connect_timeout` below, which is what turns "nothing is
        // listening" into a fast 502 instead of a hang.
        .timeout(Duration::from_secs(cfg.upstream_timeout_secs))
        .connect_timeout(Duration::from_secs(5))
        .pool_idle_timeout(Duration::from_secs(90))
        .build()?;

    let state = AppState { cfg: Arc::new(cfg), http, validator };
    let bind = state.cfg.bind;

    tracing::info!(
        component = "gateway",
        %bind,
        api_upstream = %state.cfg.api_upstream,
        engine_upstream = %state.cfg.engine_upstream,
        validator = state.validator.kind(),
        "symon-gateway starting"
    );

    let app = router::build(state);
    let listener = tokio::net::TcpListener::bind(bind).await?;

    // `into_make_service_with_connect_info` and not the bare service: without it there is no
    // `ConnectInfo` in the request extensions, `proxy::forwarded_value` has no peer address to
    // report, and every caller arrives at the rate limiter in `api.py` as 127.0.0.1.
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<std::net::SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown())
    .await?;

    tracing::info!(component = "gateway", "symon-gateway stopped");
    Ok(())
}

/// SIGTERM as well as Ctrl-C: systemd sends SIGTERM, and a service that only handles Ctrl-C
/// gets killed mid-stream on every restart.
async fn shutdown() {
    let ctrl_c = async { tokio::signal::ctrl_c().await.ok(); };
    let term = async {
        if let Ok(mut s) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            s.recv().await;
        }
    };
    tokio::select! { _ = ctrl_c => {}, _ = term => {} }
}
