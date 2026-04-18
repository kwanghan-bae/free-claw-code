#![allow(clippy::similar_names)]
// `doe` (date-of-era) and `doy` (day-of-year) are standard variable names
// from Howard Hinnant's date algorithm. Keeping them makes the algorithm
// auditable against the canonical reference.

// Computes civil (Gregorian) year/month/day from days since the Unix epoch
// (1970-01-01) using Howard Hinnant's `civil_from_days` algorithm.
#[allow(
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap,
    clippy::cast_possible_truncation
)]
pub(crate) fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 {
        z / 146_097
    } else {
        (z - 146_096) / 146_097
    };
    let doe = (z - era * 146_097) as u64; // [0, 146_096]
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let y = y + i64::from(m <= 2);
    (y as i32, m as u32, d as u32)
}
