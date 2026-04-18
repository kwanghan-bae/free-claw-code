//! Loopback-only axum listener that relays backpressure signals from the
//! sidecar (or other cooperating processes) into the Rust runtime via an
//! in-process tokio mpsc channel.
//!
//! Security: binding is rejected unless the address is a loopback interface
//! (e.g. `127.0.0.1` or `::1`). No authentication is performed on the wire
//! because the server is not intended to be reachable off-host.

use axum::{routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use tokio::sync::mpsc;

/// A backpressure signal pushed from the sidecar. The fields are intentionally
/// free-form strings so downstream interpreters (rate-limiter, UI) can evolve
/// without a wire-format break.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BackpressureSignal {
    pub level: String,
    pub reason: String,
}

/// Spawn the `/internal/backpressure` HTTP listener on a loopback address and
/// return the resolved bind address plus an mpsc receiver that yields each
/// incoming signal.
///
/// Errors if the supplied `bind` is malformed or targets a non-loopback
/// interface, or if the listener cannot be bound.
pub async fn spawn_backpressure_server(
    bind: &str,
) -> Result<(SocketAddr, mpsc::Receiver<BackpressureSignal>), String> {
    let addr: SocketAddr = bind
        .parse()
        .map_err(|e: std::net::AddrParseError| e.to_string())?;
    if !addr.ip().is_loopback() {
        return Err(format!("must bind to loopback, got {}", addr.ip()));
    }
    let (tx, rx) = mpsc::channel::<BackpressureSignal>(16);
    let tx_clone = tx.clone();
    let app = Router::new().route(
        "/internal/backpressure",
        post(move |Json(sig): Json<BackpressureSignal>| {
            let tx = tx_clone.clone();
            async move {
                let _ = tx.send(sig).await;
                axum::http::StatusCode::OK
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| e.to_string())?;
    let local_addr = listener.local_addr().map_err(|e| e.to_string())?;
    tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });
    Ok((local_addr, rx))
}
