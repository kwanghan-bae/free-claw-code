use commands::meta_cmd::{ack, fetch_alerts};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

#[tokio::test]
async fn fetch_alerts_parses_json_response() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/meta/alerts"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!([
            {"id":"a1","level":"critical","message":"x","ts":""}
        ])))
        .mount(&server)
        .await;

    let alerts = fetch_alerts(&server.uri()).await.unwrap();
    assert_eq!(alerts.len(), 1);
    assert_eq!(alerts[0].level, "critical");
    assert_eq!(alerts[0].id, "a1");
}

#[tokio::test]
async fn ack_sends_post() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/meta/ack/a1"))
        .respond_with(ResponseTemplate::new(200))
        .expect(1)
        .mount(&server)
        .await;

    ack(&server.uri(), "a1").await.unwrap();
}
