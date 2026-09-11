//! The only request shape the gateway actually parses.
//!
//! Everything under `/api/*` is forwarded opaquely — the gateway does not know or care what
//! those bodies contain, which is deliberate: `backend/api.py` owns those routes and a schema
//! duplicated here would drift from it silently. `/v1/chat/completions` is different only
//! because the WASM validator needs to count tokens in it.

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct ChatMessage {
    /// `system`, `user`, `assistant`.
    pub role: String,
    /// Optional because some clients send tool calls with a null content field.
    #[serde(default)]
    pub content: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, ToSchema)]
pub struct ChatRequest {
    #[serde(default)]
    pub model: Option<String>,

    pub messages: Vec<ChatMessage>,

    /// When true the upstream answers `text/event-stream` and the gateway forwards the frames
    /// as they arrive rather than collecting them.
    #[serde(default)]
    pub stream: bool,

    /// Anything else the engine understands is passed through untouched. Without this,
    /// adding a sampler parameter upstream would require a matching edit here — and the
    /// gateway would be silently dropping fields in the meantime.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct Health {
    /// `ok` once the process is serving. It says nothing about the upstream.
    pub status: String,
    pub version: String,
    /// Where `/api/*` is forwarded.
    pub api_upstream: String,
    /// Where `/v1/*` is forwarded.
    pub engine_upstream: String,
    /// Which validator is in force: `wasm`, or `native-fallback` when `limiter.wasm` is
    /// absent. Reported rather than hidden, because those are two different guarantees.
    pub validator: String,
    pub max_tokens: u64,
}
