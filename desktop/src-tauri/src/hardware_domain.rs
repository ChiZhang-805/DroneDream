pub(crate) fn edition_id() -> &'static str {
    env!("DRONEDREAM_DESKTOP_EDITION_ID")
}

pub(crate) fn runtime_profile() -> &'static str {
    env!("DRONEDREAM_EDITION_PROFILE")
}

pub(crate) fn require_available() -> Result<(), String> {
    match (edition_id(), runtime_profile()) {
        ("lab", "unified-sim-lab") | ("field", "field-lightweight") => Ok(()),
        _ => Err("Hardware-domain commands are unavailable in this edition".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compiled_identity_is_exact_and_hardware_scoped() {
        require_available().expect("Lab or Field hardware domain must be compiled explicitly");
        assert!(matches!(edition_id(), "lab" | "field"));
    }
}
