use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::fmt;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TraceId(pub [u8; 16]);

#[derive(Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SpanId(pub [u8; 8]);

impl TraceId {
    #[must_use]
    pub fn random() -> Self {
        loop {
            let mut bytes = [0u8; 16];
            rand::rng().fill_bytes(&mut bytes);
            let id = Self(bytes);
            if !id.is_zero() {
                return id;
            }
        }
    }
    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.0 == [0u8; 16]
    }
}

impl SpanId {
    #[must_use]
    pub fn random() -> Self {
        loop {
            let mut bytes = [0u8; 8];
            rand::rng().fill_bytes(&mut bytes);
            let id = Self(bytes);
            if !id.is_zero() {
                return id;
            }
        }
    }
    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.0 == [0u8; 8]
    }
}

impl fmt::Display for TraceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for b in &self.0 {
            write!(f, "{b:02x}")?;
        }
        Ok(())
    }
}
impl fmt::Debug for TraceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self}")
    }
}
impl fmt::Display for SpanId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for b in &self.0 {
            write!(f, "{b:02x}")?;
        }
        Ok(())
    }
}
impl fmt::Debug for SpanId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self}")
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TraceContext {
    pub trace_id: TraceId,
    pub span_id: SpanId,
    pub sampled: bool,
}

impl TraceContext {
    #[must_use]
    pub fn encode(&self) -> String {
        format!(
            "00-{}-{}-{:02x}",
            self.trace_id,
            self.span_id,
            u8::from(self.sampled)
        )
    }
    #[must_use]
    pub fn decode(header: &str) -> Option<Self> {
        let parts: Vec<&str> = header.split('-').collect();
        if parts.len() != 4 || parts[0] != "00" {
            return None;
        }
        if parts[1].len() != 32 || parts[2].len() != 16 || parts[3].len() != 2 {
            return None;
        }
        if !parts[1].is_ascii() || !parts[2].is_ascii() || !parts[3].is_ascii() {
            return None;
        }
        let mut trace = [0u8; 16];
        for (i, byte) in trace.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&parts[1][i * 2..i * 2 + 2], 16).ok()?;
        }
        let mut span = [0u8; 8];
        for (i, byte) in span.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&parts[2][i * 2..i * 2 + 2], 16).ok()?;
        }
        let flags = u8::from_str_radix(parts[3], 16).ok()?;
        Some(Self {
            trace_id: TraceId(trace),
            span_id: SpanId(span),
            sampled: flags & 1 == 1,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn traceparent_roundtrip_preserves_ids_and_flags() {
        let ctx = TraceContext {
            trace_id: TraceId([
                0x4b, 0xf9, 0x2f, 0x35, 0x77, 0xb3, 0x4d, 0xa6, 0xa3, 0xce, 0x92, 0x9d, 0x0e, 0x0e,
                0x47, 0x36,
            ]),
            span_id: SpanId([0x00, 0xf0, 0x67, 0xaa, 0x0b, 0xa9, 0x02, 0xb7]),
            sampled: true,
        };
        let header = ctx.encode();
        assert_eq!(
            header,
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        );
        let decoded = TraceContext::decode(&header).expect("roundtrip");
        assert_eq!(decoded, ctx);
    }

    #[test]
    fn traceparent_decode_rejects_bad_version() {
        assert!(
            TraceContext::decode("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
                .is_none()
        );
    }

    #[test]
    fn traceparent_decode_rejects_short_id() {
        assert!(TraceContext::decode("00-abc-def-01").is_none());
    }

    #[test]
    fn traceparent_decode_rejects_non_ascii_segments() {
        // 29 ASCII + 1 three-byte snowman: len() == 32 in bytes but non-ASCII.
        let bad = format!("00-{}\u{2603}-00f067aa0ba902b7-01", "a".repeat(29),);
        assert!(TraceContext::decode(&bad).is_none());
        // Also verify no panic on all-unicode trace segment.
        let uni_trace = "00-🦀".to_string() + &"ab".repeat(14) + "-00f067aa0ba902b7-01";
        assert!(TraceContext::decode(&uni_trace).is_none());
    }

    #[test]
    fn random_ids_are_non_zero() {
        assert!(!TraceId::random().is_zero());
        assert!(!SpanId::random().is_zero());
    }
}
