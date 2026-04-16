use api::backpressure::{BackpressureHint, BackpressureState};

#[tokio::test]
async fn backpressure_state_stores_latest_hint_per_task_type() {
    let state = BackpressureState::default();
    state
        .apply(BackpressureHint {
            task_type: "coding".into(),
            suggested_concurrency: 2,
            reason: "openrouter tpm<20%".into(),
            ttl_seconds: 60,
        })
        .await;
    state
        .apply(BackpressureHint {
            task_type: "coding".into(),
            suggested_concurrency: 1,
            reason: "groq rpm<20%".into(),
            ttl_seconds: 60,
        })
        .await;

    let current = state.current_concurrency("coding").await;
    assert_eq!(current, Some(1));

    let unknown = state.current_concurrency("planning").await;
    assert_eq!(unknown, None);
}
