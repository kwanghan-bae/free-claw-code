//! Client helpers for the sidecar's `/meta/*` endpoints.
//!
//! Powers `clawd meta {report,alerts,ack,unblock}`. All HTTP calls target
//! the local sidecar (default `http://127.0.0.1:7801`, overridable via
//! `FREE_CLAW_ROUTER_URL`).

use serde::{Deserialize, Serialize};

/// One critical, un-acknowledged alert as returned by `GET /meta/alerts`.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Alert {
    pub id: String,
    pub level: String,
    pub message: String,
    #[serde(default)]
    pub ts: String,
}

/// Resolve the sidecar base URL from env (falls back to the local default).
#[must_use]
pub fn router_url() -> String {
    std::env::var("FREE_CLAW_ROUTER_URL").unwrap_or_else(|_| "http://127.0.0.1:7801".to_string())
}

/// Fetch the list of un-acked critical alerts from the sidecar.
///
/// # Errors
/// Returns a stringified error when the HTTP call fails or the response
/// body cannot be parsed as an `Alert` list.
pub async fn fetch_alerts(sidecar_url: &str) -> Result<Vec<Alert>, String> {
    let url = format!("{}/meta/alerts", sidecar_url.trim_end_matches('/'));
    let resp = reqwest::get(&url).await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    resp.json::<Vec<Alert>>().await.map_err(|e| e.to_string())
}

/// Acknowledge a critical alert by id.
///
/// # Errors
/// Returns a stringified error when the HTTP call fails or the server
/// returns a non-success status.
pub async fn ack(sidecar_url: &str, alert_id: &str) -> Result<(), String> {
    let url = format!(
        "{}/meta/ack/{}",
        sidecar_url.trim_end_matches('/'),
        alert_id
    );
    let resp = reqwest::Client::new()
        .post(&url)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    Ok(())
}

/// Release the B-4 auto-block for a meta-edit target.
///
/// # Errors
/// Returns a stringified error when the HTTP call fails or the server
/// returns a non-success status.
pub async fn unblock(sidecar_url: &str, target: &str) -> Result<(), String> {
    let url = format!(
        "{}/meta/unblock/{}",
        sidecar_url.trim_end_matches('/'),
        target
    );
    let resp = reqwest::Client::new()
        .post(&url)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    Ok(())
}

/// Open the sidecar's `/meta/report` HTML view in the host's default
/// browser (macOS `open`, Linux `xdg-open`).
///
/// # Errors
/// Returns an I/O error when spawning the platform open command fails or
/// the command exits with a non-success status.
pub fn open_report_url(sidecar_url: &str) -> std::io::Result<()> {
    let url = format!("{}/meta/report", sidecar_url.trim_end_matches('/'));
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").arg(&url).status()?;
    #[cfg(not(target_os = "macos"))]
    let status = std::process::Command::new("xdg-open").arg(&url).status()?;
    if status.success() {
        Ok(())
    } else {
        Err(std::io::Error::other("open command failed"))
    }
}
