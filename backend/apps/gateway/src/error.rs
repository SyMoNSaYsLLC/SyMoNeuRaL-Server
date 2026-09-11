//! One error type, one JSON shape.
//!
//! The shape matches OpenAI's error envelope (`{"error": {"message", "type"}}`) because the
//! clients on the other side of `/v1/*` — `symon_client.py`, `symon_client.js`, and the Swift
//! client — are written against a llama.cpp-compatible server, and llama.cpp uses that shape.
//! A gateway that invents its own error body turns "the model refused" and "the proxy refused"
//! into two parsing paths for every client.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("payload too large: {0}")]
    PayloadTooLarge(String),

    #[error("invalid request: {0}")]
    BadRequest(String),

    /// The upstream did not answer at all — refused, timed out, or is simply not running.
    /// This is the one a caller most needs to distinguish, because on this box it usually
    /// means `symoneural-api.service` is down rather than that anything was wrong with the
    /// request. It maps to 502 so the Swift client's `backendOffline` branch is reachable.
    #[error("upstream unreachable: {0}")]
    UpstreamUnreachable(String),

    #[error("middleware failure: {0}")]
    Middleware(String),
}

impl AppError {
    fn parts(&self) -> (StatusCode, &'static str) {
        match self {
            AppError::PayloadTooLarge(_) => (StatusCode::PAYLOAD_TOO_LARGE, "payload_too_large"),
            AppError::BadRequest(_) => (StatusCode::BAD_REQUEST, "invalid_request_error"),
            AppError::UpstreamUnreachable(_) => (StatusCode::BAD_GATEWAY, "upstream_unreachable"),
            AppError::Middleware(_) => (StatusCode::INTERNAL_SERVER_ERROR, "middleware_error"),
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, kind) = self.parts();
        let message = self.to_string();

        // Log at the level the operator would want: a 502 is an incident, a 413 is a client
        // getting what it asked for.
        if status.is_server_error() {
            tracing::error!(component = "gateway", status = status.as_u16(), "{message}");
        } else {
            tracing::debug!(component = "gateway", status = status.as_u16(), "{message}");
        }

        (
            status,
            Json(json!({ "error": { "message": message, "type": kind } })),
        )
            .into_response()
    }
}
