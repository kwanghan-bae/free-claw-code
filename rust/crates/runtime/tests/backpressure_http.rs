use runtime::backpressure_server::spawn_backpressure_server;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn posts_signal_reaches_rate_limiter() {
    let (addr, mut rx) = spawn_backpressure_server("127.0.0.1:0").await.unwrap();
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("http://{addr}/internal/backpressure"))
        .json(&serde_json::json!({"level": "warn", "reason": "quota-near"}))
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 200);
    let sig = rx.recv().await.unwrap();
    assert_eq!(sig.level, "warn");
    assert_eq!(sig.reason, "quota-near");
}

#[tokio::test]
async fn rejects_non_loopback_binding() {
    let err = spawn_backpressure_server("0.0.0.0:0").await;
    assert!(err.is_err());
    let msg = format!("{:?}", err.unwrap_err());
    assert!(
        msg.to_lowercase().contains("loopback"),
        "expected loopback error, got: {msg}"
    );
}
