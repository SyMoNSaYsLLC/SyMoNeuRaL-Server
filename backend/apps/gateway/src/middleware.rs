//! Payload validation, executed in a WebAssembly sandbox.
//!
//! ## Why this is not `GOOS=js`
//!
//! The original spec said to compile the Go validator with `GOOS=js GOARCH=wasm`. That target
//! **cannot be loaded by Wasmtime.** It emits a module whose imports are all in the `gojs`
//! namespace and which expects `wasm_exec.js` — a JavaScript runtime — to supply them. A
//! standalone WASM host has no JavaScript, so `Module::from_file` fails at instantiation with
//! unknown-import errors rather than at build time, which is a confusing place to find out.
//!
//! The target that works in a standalone host is `wasip1` (Go 1.21+), with exports declared
//! via `//go:wasmexport` (Go 1.24+). `ops/middleware/limiter.go` is written for that and
//! carries the exact build command.
//!
//! ## The ABI, which is three functions
//!
//! WebAssembly passes integers, not strings, so the guest must lend the host some memory:
//!
//! - `sym_alloc(len: i32) -> i32` — guest allocates `len` bytes, returns the offset.
//! - `sym_validate(ptr: i32, len: i32) -> i64` — reads the JSON at `ptr`, returns the result
//!   packed as `(offset << 32) | len` so a single i64 carries both halves of a slice.
//! - `sym_free(ptr: i32, len: i32)` — releases what `sym_validate` returned.
//!
//! ## Absent is a supported state
//!
//! Go is not installed on this box, so `limiter.wasm` does not exist yet and the gateway must
//! still run. When the file is missing the same rule is enforced natively and `/healthz`
//! reports `validator: "native-fallback"`. It says so rather than quietly appearing to be
//! sandboxed — an unenforced limit that *looks* enforced is the failure worth avoiding.

use std::path::Path;
use std::sync::Arc;

use tokio::sync::Mutex;
use wasmtime::{Engine, Instance, Linker, Memory, Module, Store, TypedFunc};
use wasmtime_wasi::preview1::{self, WasiP1Ctx};
use wasmtime_wasi::WasiCtxBuilder;

use crate::error::AppError;

/// The verdict the validator returns. Shared by both implementations so the fallback cannot
/// drift into a different answer shape.
#[derive(Debug, serde::Deserialize)]
struct Verdict {
    ok: bool,
    #[serde(default)]
    tokens: u64,
    #[serde(default)]
    message: String,
}

pub struct Validator {
    max_tokens: u64,
    /// `None` when `limiter.wasm` is absent.
    ///
    /// A `wasmtime::Store` is not `Sync` and an `Instance` is bound to its store, so the
    /// instance cannot be shared across the Tokio worker threads that Axum hands requests to.
    /// The Mutex serialises access to the one instance. That is acceptable *only* because the
    /// validator is a whitespace scan measured in microseconds; anything doing real work here
    /// would need an instance pool instead, and this comment is here so that decision is made
    /// deliberately rather than discovered under load.
    wasm: Option<Mutex<WasmValidator>>,
}

struct WasmValidator {
    store: Store<WasiP1Ctx>,
    memory: Memory,
    alloc: TypedFunc<i32, i32>,
    validate: TypedFunc<(i32, i32), i64>,
    free: TypedFunc<(i32, i32), ()>,
}

impl Validator {
    /// Loads the module if it is there. A *present but broken* module is a hard error — that
    /// is a deployment mistake and should stop the process, unlike the absence above which is
    /// simply the state of this box today.
    pub fn load(wasm_path: &Path, max_tokens: u64) -> anyhow::Result<Arc<Self>> {
        if !wasm_path.exists() {
            tracing::warn!(
                component = "gateway",
                path = %wasm_path.display(),
                "limiter.wasm not found -- enforcing the token ceiling natively. \
                 Build it with `make build-wasm` (needs Go 1.24+) to run the sandboxed validator."
            );
            return Ok(Arc::new(Self { max_tokens, wasm: None }));
        }

        let engine = Engine::default();
        let module = Module::from_file(&engine, wasm_path)?;

        let mut linker: Linker<WasiP1Ctx> = Linker::new(&engine);
        preview1::add_to_linker_sync(&mut linker, |t| t)?;

        // No preopened directories, no environment, no argv, no network. The validator reads
        // the bytes it is handed and returns a verdict; it has no business touching anything
        // else, and a sandbox that grants more than the job needs is not doing its job.
        let wasi = WasiCtxBuilder::new().build_p1();
        let mut store = Store::new(&engine, wasi);

        let instance: Instance = linker.instantiate(&mut store, &module)?;

        let memory = instance
            .get_memory(&mut store, "memory")
            .ok_or_else(|| anyhow::anyhow!("limiter.wasm exports no `memory`"))?;
        let alloc = instance.get_typed_func::<i32, i32>(&mut store, "sym_alloc")?;
        let validate = instance.get_typed_func::<(i32, i32), i64>(&mut store, "sym_validate")?;
        let free = instance.get_typed_func::<(i32, i32), ()>(&mut store, "sym_free")?;

        // Go's wasip1 runtime needs `_start` run once before any `//go:wasmexport` function is
        // called, or the scheduler and allocator it relies on are not initialised. Under
        // Go 1.24+ `_start` returns rather than exiting, precisely so the module can go on
        // serving exported calls.
        if let Ok(start) = instance.get_typed_func::<(), ()>(&mut store, "_start") {
            start.call(&mut store, ())?;
        }

        tracing::info!(
            component = "gateway",
            path = %wasm_path.display(),
            "WASM validator loaded"
        );

        Ok(Arc::new(Self {
            max_tokens,
            wasm: Some(Mutex::new(WasmValidator { store, memory, alloc, validate, free })),
        }))
    }

    pub fn kind(&self) -> &'static str {
        if self.wasm.is_some() { "wasm" } else { "native-fallback" }
    }

    /// Returns the estimated token count, or the error that should go back to the caller.
    pub async fn check(&self, payload: &[u8]) -> Result<u64, AppError> {
        let verdict = match &self.wasm {
            Some(m) => {
                let mut guard = m.lock().await;
                guard.run(payload).map_err(|e| AppError::Middleware(e.to_string()))?
            }
            None => native_verdict(payload, self.max_tokens)?,
        };

        if verdict.ok {
            Ok(verdict.tokens)
        } else {
            Err(AppError::PayloadTooLarge(verdict.message))
        }
    }
}

impl WasmValidator {
    fn run(&mut self, payload: &[u8]) -> anyhow::Result<Verdict> {
        let len = i32::try_from(payload.len())
            .map_err(|_| anyhow::anyhow!("payload exceeds the 2 GiB wasm addressable limit"))?;

        let ptr = self.alloc.call(&mut self.store, len)?;
        if ptr == 0 {
            anyhow::bail!("guest allocation failed");
        }
        self.memory.write(&mut self.store, ptr as usize, payload)?;

        let packed = self.validate.call(&mut self.store, (ptr, len))?;
        self.free.call(&mut self.store, (ptr, len))?;

        let out_ptr = (packed >> 32) as i32;
        let out_len = (packed & 0xFFFF_FFFF) as i32;
        if out_ptr == 0 || out_len <= 0 {
            anyhow::bail!("validator returned an empty verdict");
        }

        let mut buf = vec![0u8; out_len as usize];
        self.memory.read(&self.store, out_ptr as usize, &mut buf)?;
        self.free.call(&mut self.store, (out_ptr, out_len))?;

        Ok(serde_json::from_slice(&buf)?)
    }
}

/// The same rule as `ops/middleware/limiter.go`, in Rust, for when the module is absent.
///
/// Both count whitespace-separated words in every `content` field. That is an *estimate* and
/// is named one everywhere it appears: real BPE tokenisation runs roughly 1.3x higher for
/// English prose and far higher for code. It is here to stop a runaway payload before it
/// reaches the GPU, not to bill anyone.
fn native_verdict(payload: &[u8], max_tokens: u64) -> Result<Verdict, AppError> {
    let v: serde_json::Value = serde_json::from_slice(payload)
        .map_err(|e| AppError::BadRequest(format!("body is not valid JSON: {e}")))?;

    let mut tokens: u64 = 0;
    if let Some(messages) = v.get("messages").and_then(|m| m.as_array()) {
        for m in messages {
            if let Some(c) = m.get("content").and_then(|c| c.as_str()) {
                tokens += c.split_whitespace().count() as u64;
            }
        }
    }

    if tokens > max_tokens {
        Ok(Verdict {
            ok: false,
            tokens,
            message: format!(
                "estimated {tokens} tokens exceeds the {max_tokens} ceiling (whitespace estimate)"
            ),
        })
    } else {
        Ok(Verdict { ok: true, tokens, message: String::new() })
    }
}
