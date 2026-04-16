use std::collections::HashMap;
use std::sync::Arc;

use api::{AnthropicClient, AuthSource, InputContentBlock, InputMessage, MessageRequest};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::sync::Mutex;

/// Verify that `AnthropicClient::with_hints` causes the outbound HTTP request
/// to carry the `x-free-claw-hints` header with the provided hint value.
#[tokio::test]
async fn anthropic_client_emits_hints_header_when_set() {
    let state = Arc::new(Mutex::new(Vec::<CapturedRequest>::new()));
    let body = concat!(
        "{",
        "\"id\":\"msg_h1\",",
        "\"type\":\"message\",",
        "\"role\":\"assistant\",",
        "\"content\":[{\"type\":\"text\",\"text\":\"ok\"}],",
        "\"model\":\"claude-3-7-sonnet-latest\",",
        "\"stop_reason\":\"end_turn\",",
        "\"stop_sequence\":null,",
        "\"usage\":{\"input_tokens\":5,\"output_tokens\":1}",
        "}"
    );
    let server = spawn_server(
        state.clone(),
        vec![http_response("200 OK", "application/json", body)],
    )
    .await;

    let client = AnthropicClient::from_auth(AuthSource::ApiKey("test-key".into()))
        .with_base_url(server.base_url())
        .with_hints("coding");

    let _ = client.send_message(&sample_request()).await;

    let captured = state.lock().await;
    let request = captured.first().expect("server should capture request");
    assert_eq!(
        request.headers.get("x-free-claw-hints").map(String::as_str),
        Some("coding"),
        "outbound request must carry the x-free-claw-hints header"
    );
}

/// Verify that when no hints are set, no `x-free-claw-hints` header is sent.
#[tokio::test]
async fn anthropic_client_omits_hints_header_when_not_set() {
    let state = Arc::new(Mutex::new(Vec::<CapturedRequest>::new()));
    let body = concat!(
        "{",
        "\"id\":\"msg_h2\",",
        "\"type\":\"message\",",
        "\"role\":\"assistant\",",
        "\"content\":[{\"type\":\"text\",\"text\":\"ok\"}],",
        "\"model\":\"claude-3-7-sonnet-latest\",",
        "\"stop_reason\":\"end_turn\",",
        "\"stop_sequence\":null,",
        "\"usage\":{\"input_tokens\":5,\"output_tokens\":1}",
        "}"
    );
    let server = spawn_server(
        state.clone(),
        vec![http_response("200 OK", "application/json", body)],
    )
    .await;

    let client = AnthropicClient::from_auth(AuthSource::ApiKey("test-key".into()))
        .with_base_url(server.base_url());

    let _ = client.send_message(&sample_request()).await;

    let captured = state.lock().await;
    let request = captured.first().expect("server should capture request");
    assert!(
        !request.headers.contains_key("x-free-claw-hints"),
        "outbound request must NOT carry x-free-claw-hints when no hints are set"
    );
}

// ---------------------------------------------------------------------------
// Test infrastructure (mirrors traceparent_emission.rs)
// ---------------------------------------------------------------------------

fn sample_request() -> MessageRequest {
    MessageRequest {
        model: "claude-3-7-sonnet-latest".to_string(),
        max_tokens: 64,
        messages: vec![InputMessage {
            role: "user".to_string(),
            content: vec![InputContentBlock::Text {
                text: "ping".to_string(),
            }],
        }],
        ..MessageRequest::default()
    }
}

struct CapturedRequest {
    #[allow(dead_code)]
    method: String,
    #[allow(dead_code)]
    path: String,
    headers: HashMap<String, String>,
    #[allow(dead_code)]
    body: String,
}

struct TestServer {
    base_url: String,
    join_handle: tokio::task::JoinHandle<()>,
}

impl TestServer {
    fn base_url(&self) -> String {
        self.base_url.clone()
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.join_handle.abort();
    }
}

async fn spawn_server(
    state: Arc<Mutex<Vec<CapturedRequest>>>,
    responses: Vec<String>,
) -> TestServer {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("listener should bind");
    let address = listener
        .local_addr()
        .expect("listener should have local addr");
    let join_handle = tokio::spawn(async move {
        for response in responses {
            let (mut socket, _) = listener.accept().await.expect("server should accept");
            let mut buffer = Vec::new();
            let mut header_end = None;

            loop {
                let mut chunk = [0_u8; 1024];
                let read = socket
                    .read(&mut chunk)
                    .await
                    .expect("request read should succeed");
                if read == 0 {
                    break;
                }
                buffer.extend_from_slice(&chunk[..read]);
                if let Some(position) = find_header_end(&buffer) {
                    header_end = Some(position);
                    break;
                }
            }

            let header_end = header_end.expect("request should include headers");
            let (header_bytes, remaining) = buffer.split_at(header_end);
            let header_text =
                String::from_utf8(header_bytes.to_vec()).expect("headers should be utf8");
            let mut lines = header_text.split("\r\n");
            let request_line = lines.next().expect("request line should exist");
            let mut parts = request_line.split_whitespace();
            let method = parts.next().expect("method should exist").to_string();
            let path = parts.next().expect("path should exist").to_string();
            let mut headers = HashMap::new();
            let mut content_length = 0_usize;
            for line in lines {
                if line.is_empty() {
                    continue;
                }
                let (name, value) = line.split_once(':').expect("header should have colon");
                let value = value.trim().to_string();
                if name.eq_ignore_ascii_case("content-length") {
                    content_length = value.parse().expect("content length should parse");
                }
                headers.insert(name.to_ascii_lowercase(), value);
            }

            let mut body = remaining[4..].to_vec();
            while body.len() < content_length {
                let mut chunk = vec![0_u8; content_length - body.len()];
                let read = socket
                    .read(&mut chunk)
                    .await
                    .expect("body read should succeed");
                if read == 0 {
                    break;
                }
                body.extend_from_slice(&chunk[..read]);
            }

            state.lock().await.push(CapturedRequest {
                method,
                path,
                headers,
                body: String::from_utf8(body).expect("body should be utf8"),
            });

            socket
                .write_all(response.as_bytes())
                .await
                .expect("response write should succeed");
        }
    });

    TestServer {
        base_url: format!("http://{address}"),
        join_handle,
    }
}

fn find_header_end(bytes: &[u8]) -> Option<usize> {
    bytes.windows(4).position(|window| window == b"\r\n\r\n")
}

fn http_response(status: &str, content_type: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 {status}\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
        body.len()
    )
}
