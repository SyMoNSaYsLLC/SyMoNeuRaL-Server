// Command limiter is the payload validator that runs inside the gateway's WASM sandbox.
//
// # Build
//
//	GOOS=wasip1 GOARCH=wasm go build -o ops/middleware/limiter.wasm ./ops/middleware
//
// # NOT `GOOS=js`
//
// The obvious-looking `GOOS=js GOARCH=wasm` is wrong for this and fails in a confusing place.
// That target emits a module whose imports all sit in the `gojs` namespace and which expects
// `wasm_exec.js` to supply them, because it is meant to run inside a browser. Wasmtime has no
// JavaScript to offer it, so the failure arrives at *instantiation* — a wall of unknown-import
// errors — rather than at build time. `wasip1` is the target for a standalone host.
//
// # Requires Go 1.24 or newer
//
// `//go:wasmexport` landed in Go 1.24. Before that, a wasip1 module could only be entered
// through `main`, which is no use to a host that wants to call a function per request. Go is
// not currently installed on this machine; `make build-wasm` will say so rather than emit a
// broken artefact, and until it is built the gateway enforces the same ceiling natively and
// reports `validator: "native-fallback"` on /healthz.
//
// # ABI
//
// WebAssembly passes numbers, not strings, so the host borrows guest memory:
//
//	sym_alloc(len)        -> ptr          guest-owned buffer for the host to write into
//	sym_validate(ptr,len) -> ptr<<32|len  a JSON verdict, packed into one i64
//	sym_free(ptr,len)                     release either of the above
//
// Every buffer handed out here is pinned in `live` until freed. Without that the collector is
// free to move or reclaim it the moment `sym_validate` returns, and the host would read
// whatever landed there next — intermittently, under load, which is the worst way to find out.
package main

import (
	"encoding/json"
	"strings"
	"unsafe"
)

// maxTokens mirrors SYMON_MAX_TOKENS in the gateway. It is duplicated rather than passed in
// because the ceiling is policy and belongs with the code that enforces it; if they disagree
// the gateway's /healthz is the place that will show it.
const maxTokens = 100000

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequest struct {
	Model    string    `json:"model"`
	Messages []message `json:"messages"`
}

type verdict struct {
	OK      bool   `json:"ok"`
	Tokens  uint64 `json:"tokens"`
	Message string `json:"message,omitempty"`
}

// live keeps every outstanding buffer reachable so the GC cannot collect or move it while the
// host holds a raw pointer to it.
var live = map[uintptr][]byte{}

//go:wasmexport sym_alloc
func symAlloc(size int32) int32 {
	if size <= 0 {
		return 0
	}
	buf := make([]byte, size)
	ptr := uintptr(unsafe.Pointer(&buf[0]))
	live[ptr] = buf
	return int32(ptr)
}

//go:wasmexport sym_free
func symFree(ptr int32, _ int32) {
	delete(live, uintptr(ptr))
}

//go:wasmexport sym_validate
func symValidate(ptr int32, length int32) int64 {
	body := unsafe.Slice((*byte)(unsafe.Pointer(uintptr(ptr))), int(length))

	var req chatRequest
	if err := json.Unmarshal(body, &req); err != nil {
		// Malformed JSON is refused here rather than forwarded. The engine would reject it
		// anyway, but only after the request has been queued behind the GPU lock.
		return emit(verdict{OK: false, Message: "payload is not valid JSON: " + err.Error()})
	}

	var tokens uint64
	for _, m := range req.Messages {
		tokens += uint64(len(strings.Fields(m.Content)))
	}

	if tokens > maxTokens {
		return emit(verdict{
			OK:      false,
			Tokens:  tokens,
			Message: "estimated " + itoa(tokens) + " tokens exceeds the " + itoa(maxTokens) +
				" ceiling (whitespace estimate)",
		})
	}
	return emit(verdict{OK: true, Tokens: tokens})
}

// emit serialises v into a guest buffer and packs its address and length into one i64, high
// word first. A single return value keeps the host side free of out-params.
func emit(v verdict) int64 {
	out, err := json.Marshal(v)
	if err != nil {
		out = []byte(`{"ok":false,"message":"validator could not encode its own verdict"}`)
	}
	ptr := symAlloc(int32(len(out)))
	if ptr == 0 {
		return 0
	}
	copy(live[uintptr(ptr)], out)
	return int64(ptr)<<32 | int64(len(out))
}

// itoa avoids strconv purely to keep the module small; this is the only number it formats.
func itoa(n uint64) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

// main must exist and must return. Under wasip1 the host calls `_start`, which runs main and,
// since Go 1.24, leaves the instance alive so the exported functions above stay callable.
func main() {}
