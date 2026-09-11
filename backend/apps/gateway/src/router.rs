//! Route table and the OpenAPI document.
//!
//! Axum 0.8 changed wildcard syntax from `/*path` to `/{*path}`. The old form does not warn —
//! it is read as a literal path segment named `*path`, so the route silently never matches and
//! every request falls through to 404.

use axum::routing::{any, get};
use axum::Router;
use tower_http::trace::TraceLayer;
use utoipa::OpenApi;
use utoipa_swagger_ui::SwaggerUi;

use crate::models::{ChatMessage, ChatRequest, Health};
use crate::proxy;
use crate::AppState;

#[derive(OpenApi)]
#[openapi(
    paths(
        proxy::healthz,
        proxy::proxy_api,
        proxy::chat_completions,
        proxy::proxy_v1,
    ),
    components(schemas(ChatRequest, ChatMessage, Health)),
    tags(
        (name = "gateway", description = "The gateway's own surface"),
        (name = "proxy", description = "Forwarded verbatim to backend/api.py on :8800. \
             The gateway makes no routing decision here and rewrites nothing; FastAPI still \
             owns every path under /api."),
        (name = "inference", description = "OpenAI-compatible surface. Chat payloads are \
             validated in a WASM sandbox before they are forwarded, so an oversized request \
             is refused before anything takes the GPU lock."),
    ),
    info(
        title = "SyMoNeuRaL Gateway",
        description = "Front door for symoneural.com. Streams by default: SSE frames are \
            forwarded as they arrive, never collected.",
    )
)]
pub struct ApiDoc;

pub fn build(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(proxy::healthz))
        // Both the bare prefix and everything under it. `/{*path}` does not match the empty
        // remainder, so without the first line `POST /api` is a 404 while `POST /api/chat`
        // works -- an inconsistency that is tedious to debug from the client side.
        .route("/api", any(proxy::proxy_api))
        .route("/api/{*path}", any(proxy::proxy_api))
        // Listed before the `/v1` wildcard. Axum matches the more specific literal path
        // regardless of declaration order, but keeping them adjacent makes the precedence
        // visible to whoever adds the next route.
        .route("/v1/chat/completions", any(proxy::chat_completions))
        .route("/v1/{*path}", any(proxy::proxy_v1))
        .layer(TraceLayer::new_for_http())
        // `with_state` before the merge, not after. `SwaggerUi` converts into a `Router<()>`,
        // so merging it into a still-stateful `Router<AppState>` does not typecheck -- the
        // error names `From<SwaggerUi>` and reads as though the feature flags are wrong.
        .with_state(state)
        .merge(SwaggerUi::new("/swagger-ui").url("/api-docs/openapi.json", ApiDoc::openapi()))
}
