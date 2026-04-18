//! Bridge between `CronCreate` command invocations and the Python sidecar's
//! `/cron/register` HTTP endpoint.
//!
//! When the sidecar is reachable the cron spec is posted as JSON. When the
//! request fails for any reason, [`register_cron_with_fallback`] persists the
//! spec to a local directory as `<job_id>.json` so no scheduling intent is
//! lost.

use serde::{Deserialize, Serialize};
use std::path::Path;

/// A cron registration request shipped to the sidecar (or written to the
/// fallback directory verbatim).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CronSpec {
    pub job_id: String,
    pub cron_expr: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, thiserror::Error)]
pub enum CronError {
    #[error("sidecar error: {0}")]
    Sidecar(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("serialization error: {0}")]
    Serde(String),
}

/// POST a cron spec to the sidecar's `/cron/register` endpoint.
///
/// `sidecar_url` should be the base URL (scheme + host + port); any trailing
/// slash is trimmed so both `http://host` and `http://host/` behave the same.
pub async fn register_cron(sidecar_url: &str, spec: &CronSpec) -> Result<(), CronError> {
    let client = reqwest::Client::new();
    let url = format!("{}/cron/register", sidecar_url.trim_end_matches('/'));
    let resp = client
        .post(&url)
        .json(spec)
        .send()
        .await
        .map_err(|e| CronError::Sidecar(e.to_string()))?;
    if !resp.status().is_success() {
        return Err(CronError::Sidecar(format!("status {}", resp.status())));
    }
    Ok(())
}

/// Attempt a sidecar registration; on failure, persist the spec to
/// `fallback_dir/<job_id>.json` so the scheduling intent is preserved for a
/// later replay.
pub async fn register_cron_with_fallback(
    sidecar_url: &str,
    spec: &CronSpec,
    fallback_dir: &Path,
) -> Result<(), CronError> {
    if register_cron(sidecar_url, spec).await.is_ok() {
        return Ok(());
    }
    std::fs::create_dir_all(fallback_dir)?;
    let path = fallback_dir.join(format!("{}.json", spec.job_id));
    let bytes = serde_json::to_vec_pretty(spec).map_err(|e| CronError::Serde(e.to_string()))?;
    std::fs::write(path, bytes)?;
    Ok(())
}
