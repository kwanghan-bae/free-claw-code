use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BackpressureHint {
    pub task_type: String,
    pub suggested_concurrency: u32,
    pub reason: String,
    pub ttl_seconds: u64,
}

#[derive(Clone, Default)]
pub struct BackpressureState {
    inner: Arc<RwLock<HashMap<String, (BackpressureHint, std::time::Instant)>>>,
}

impl BackpressureState {
    pub async fn apply(&self, hint: BackpressureHint) {
        let mut guard = self.inner.write().await;
        guard.insert(hint.task_type.clone(), (hint, std::time::Instant::now()));
    }
    pub async fn current_concurrency(&self, task_type: &str) -> Option<u32> {
        let guard = self.inner.read().await;
        let (hint, applied_at) = guard.get(task_type)?;
        let age = applied_at.elapsed().as_secs();
        if age > hint.ttl_seconds {
            return None;
        }
        Some(hint.suggested_concurrency)
    }
}
