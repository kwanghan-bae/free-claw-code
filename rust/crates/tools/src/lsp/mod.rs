//! LSP tool handler (language-server registry dispatch).
//! Extracted from tools/src/lib.rs under P5 A-2 for single-responsibility modules.

use serde::Deserialize;
use serde_json::json;

use crate::{global_lsp_registry, to_pretty_json};

#[derive(Debug, Deserialize)]
pub(crate) struct LspInput {
    action: String,
    #[serde(default)]
    path: Option<String>,
    #[serde(default)]
    line: Option<u32>,
    #[serde(default)]
    character: Option<u32>,
    #[serde(default)]
    query: Option<String>,
}

#[allow(clippy::needless_pass_by_value)]
pub(crate) fn run_lsp(input: LspInput) -> Result<String, String> {
    let registry = global_lsp_registry();
    let action = &input.action;
    let path = input.path.as_deref();
    let line = input.line;
    let character = input.character;
    let query = input.query.as_deref();

    match registry.dispatch(action, path, line, character, query) {
        Ok(result) => to_pretty_json(result),
        Err(e) => to_pretty_json(json!({
            "action": action,
            "error": e,
            "status": "error"
        })),
    }
}
