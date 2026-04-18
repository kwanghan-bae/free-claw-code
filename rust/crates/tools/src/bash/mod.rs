//! Bash tool helpers (bash command execution, workspace-test preflight).
//! Extracted from tools/src/lib.rs under P5 A-2 for single-responsibility modules.

use std::path::PathBuf;

use runtime::{
    check_freshness, execute_bash, BashCommandInput, BashCommandOutput, BranchFreshness,
    LaneEvent, LaneEventName, LaneEventStatus, LaneFailureClass, PermissionMode,
};
use serde_json::json;

use crate::git::{git_stdout, resolve_main_ref};
use crate::iso8601_now;

/// Classify bash command permission based on command type and path.
/// ROADMAP #50: Read-only commands targeting CWD paths get `WorkspaceWrite`,
/// all others remain `DangerFullAccess`.
pub(crate) fn classify_bash_permission(command: &str) -> PermissionMode {
    // Read-only commands that are safe when targeting workspace paths
    const READ_ONLY_COMMANDS: &[&str] = &[
        "cat", "head", "tail", "less", "more", "ls", "ll", "dir", "find", "test", "[", "[[",
        "grep", "rg", "awk", "sed", "file", "stat", "readlink", "wc", "sort", "uniq", "cut", "tr",
        "pwd", "echo", "printf",
    ];

    // Get the base command (first word before any args or pipes)
    let base_cmd = command.split_whitespace().next().unwrap_or("");
    let base_cmd = base_cmd.split('|').next().unwrap_or("").trim();
    let base_cmd = base_cmd.split(';').next().unwrap_or("").trim();
    let base_cmd = base_cmd.split('>').next().unwrap_or("").trim();
    let base_cmd = base_cmd.split('<').next().unwrap_or("").trim();

    // Check if it's a read-only command
    let cmd_name = base_cmd.split('/').next_back().unwrap_or(base_cmd);
    let is_read_only = READ_ONLY_COMMANDS.contains(&cmd_name);

    if !is_read_only {
        return PermissionMode::DangerFullAccess;
    }

    // Check if any path argument is outside workspace
    // Simple heuristic: check for absolute paths not starting with CWD
    if has_dangerous_paths(command) {
        return PermissionMode::DangerFullAccess;
    }

    PermissionMode::WorkspaceWrite
}

/// Check if command has dangerous paths (outside workspace).
fn has_dangerous_paths(command: &str) -> bool {
    // Look for absolute paths
    let tokens: Vec<&str> = command.split_whitespace().collect();

    for token in tokens {
        // Skip flags/options
        if token.starts_with('-') {
            continue;
        }

        // Check for absolute paths
        if token.starts_with('/') || token.starts_with("~/") {
            // Check if it's within CWD
            let path =
                PathBuf::from(token.replace('~', &std::env::var("HOME").unwrap_or_default()));
            if let Ok(cwd) = std::env::current_dir() {
                if !path.starts_with(&cwd) {
                    return true; // Path outside workspace
                }
            }
        }

        // Check for parent directory traversal that escapes workspace
        if token.contains("../..") || token.starts_with("../") && !token.starts_with("./") {
            return true;
        }
    }

    false
}

pub(crate) fn run_bash(input: BashCommandInput) -> Result<String, String> {
    if let Some(output) = workspace_test_branch_preflight(&input.command) {
        return serde_json::to_string_pretty(&output).map_err(|error| error.to_string());
    }
    serde_json::to_string_pretty(&execute_bash(input).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())
}

pub(crate) fn workspace_test_branch_preflight(command: &str) -> Option<BashCommandOutput> {
    if !is_workspace_test_command(command) {
        return None;
    }

    let branch = git_stdout(&["branch", "--show-current"])?;
    let main_ref = resolve_main_ref(&branch)?;
    let freshness = check_freshness(&branch, &main_ref);
    match freshness {
        BranchFreshness::Fresh => None,
        BranchFreshness::Stale {
            commits_behind,
            missing_fixes,
        } => Some(branch_divergence_output(
            command,
            &branch,
            &main_ref,
            commits_behind,
            None,
            &missing_fixes,
        )),
        BranchFreshness::Diverged {
            ahead,
            behind,
            missing_fixes,
        } => Some(branch_divergence_output(
            command,
            &branch,
            &main_ref,
            behind,
            Some(ahead),
            &missing_fixes,
        )),
    }
}

fn is_workspace_test_command(command: &str) -> bool {
    let normalized = normalize_shell_command(command);
    [
        "cargo test --workspace",
        "cargo test --all",
        "cargo nextest run --workspace",
        "cargo nextest run --all",
    ]
    .iter()
    .any(|needle| normalized.contains(needle))
}

fn normalize_shell_command(command: &str) -> String {
    command
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn branch_divergence_output(
    command: &str,
    branch: &str,
    main_ref: &str,
    commits_behind: usize,
    commits_ahead: Option<usize>,
    missing_fixes: &[String],
) -> BashCommandOutput {
    let relation = commits_ahead.map_or_else(
        || format!("is {commits_behind} commit(s) behind"),
        |ahead| format!("has diverged ({ahead} ahead, {commits_behind} behind)"),
    );
    let missing_summary = if missing_fixes.is_empty() {
        "(none surfaced)".to_string()
    } else {
        missing_fixes.join("; ")
    };
    let stderr = format!(
        "branch divergence detected before workspace tests: `{branch}` {relation} `{main_ref}`. Missing commits: {missing_summary}. Merge or rebase `{main_ref}` before re-running `{command}`."
    );

    BashCommandOutput {
        stdout: String::new(),
        stderr: stderr.clone(),
        raw_output_path: None,
        interrupted: false,
        is_image: None,
        background_task_id: None,
        backgrounded_by_user: None,
        assistant_auto_backgrounded: None,
        dangerously_disable_sandbox: None,
        return_code_interpretation: Some("preflight_blocked:branch_divergence".to_string()),
        no_output_expected: Some(false),
        structured_content: Some(vec![serde_json::to_value(
            LaneEvent::new(
                LaneEventName::BranchStaleAgainstMain,
                LaneEventStatus::Blocked,
                iso8601_now(),
            )
            .with_failure_class(LaneFailureClass::BranchDivergence)
            .with_detail(stderr.clone())
            .with_data(json!({
                "branch": branch,
                "mainRef": main_ref,
                "commitsBehind": commits_behind,
                "commitsAhead": commits_ahead,
                "missingCommits": missing_fixes,
                "blockedCommand": command,
                "recommendedAction": format!("merge or rebase {main_ref} before workspace tests")
            })),
        )
        .expect("lane event should serialize")]),
        persisted_output_path: None,
        persisted_output_size: None,
        sandbox_status: None,
    }
}
