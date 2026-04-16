use serde::Deserialize;

#[derive(Debug, Clone)]
pub(crate) struct RouterHealthReport {
    pub(crate) healthy: bool,
    pub(crate) catalog_version: Option<String>,
    pub(crate) error: Option<String>,
}

#[derive(Deserialize)]
struct HealthBody {
    status: String,
    #[serde(default)]
    catalog_version: Option<String>,
}

pub(crate) async fn router_health_probe(base_url: &str) -> RouterHealthReport {
    let url = format!("{}/health", base_url.trim_end_matches('/'));
    match reqwest::Client::new().get(&url).send().await {
        Ok(resp) if resp.status().is_success() => match resp.json::<HealthBody>().await {
            Ok(body) => RouterHealthReport {
                healthy: body.status == "ok",
                catalog_version: body.catalog_version,
                error: None,
            },
            Err(e) => RouterHealthReport {
                healthy: false,
                catalog_version: None,
                error: Some(e.to_string()),
            },
        },
        Ok(resp) => RouterHealthReport {
            healthy: false,
            catalog_version: None,
            error: Some(format!("http {}", resp.status())),
        },
        Err(e) => RouterHealthReport {
            healthy: false,
            catalog_version: None,
            error: Some(e.to_string()),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use httpmock::{Method::GET, MockServer};

    #[tokio::test]
    async fn doctor_reports_router_health_when_sidecar_up() {
        let server = MockServer::start();
        server.mock(|when, then| {
            when.method(GET).path("/health");
            then.status(200)
                .body("{\"status\":\"ok\",\"catalog_version\":\"2026-04-15\"}");
        });

        let report = router_health_probe(&server.base_url()).await;
        assert!(report.healthy);
        assert_eq!(report.catalog_version.as_deref(), Some("2026-04-15"));
    }

    #[tokio::test]
    async fn doctor_reports_router_unhealthy_on_connection_refused() {
        let report = router_health_probe("http://127.0.0.1:1").await;
        assert!(!report.healthy);
        assert!(report.error.is_some());
    }
}
