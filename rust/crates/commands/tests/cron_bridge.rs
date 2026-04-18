// dev-deps needed: wiremock = "0.6", tempfile = "3", tokio = { features = ["macros","rt"] }
use commands::cron::{register_cron, register_cron_with_fallback, CronSpec};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

#[tokio::test]
async fn register_cron_posts_to_sidecar() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/cron/register"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(serde_json::json!({"ok": true, "job_id": "abc"})),
        )
        .expect(1)
        .mount(&server)
        .await;

    let spec = CronSpec {
        job_id: "abc".into(),
        cron_expr: "*/5 * * * *".into(),
        payload: serde_json::json!({"task": "ping"}),
    };
    let result = register_cron(&server.uri(), &spec).await;
    assert!(result.is_ok(), "got {result:?}");
}

#[tokio::test]
async fn register_cron_falls_back_on_error() {
    let fallback_dir = tempfile::tempdir().unwrap();
    let spec = CronSpec {
        job_id: "xyz".into(),
        cron_expr: "0 0 * * *".into(),
        payload: serde_json::json!({}),
    };
    // Use an unused loopback port to force connection error
    let result = register_cron_with_fallback("http://127.0.0.1:1", &spec, fallback_dir.path()).await;
    assert!(result.is_ok());
    assert!(fallback_dir.path().join("xyz.json").exists());
}
