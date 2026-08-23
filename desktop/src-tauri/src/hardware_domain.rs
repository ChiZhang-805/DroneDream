pub(crate) fn edition_id() -> &'static str {
    match env!("DRONEDREAM_DESKTOP_EDITION_ID") {
        // Universal embeds the mature FIELD hardware-domain module alongside
        // the LAB calibration module. It never creates a new authority
        // domain: hardware receipts continue to use the canonical FIELD id.
        "universal" => "field",
        edition => edition,
    }
}

pub(crate) fn runtime_profile() -> &'static str {
    env!("DRONEDREAM_EDITION_PROFILE")
}

pub(crate) fn require_available() -> Result<(), String> {
    match (env!("DRONEDREAM_DESKTOP_EDITION_ID"), runtime_profile()) {
        ("universal", "unified-sim-lab")
        | ("lab", "unified-sim-lab")
        | ("field", "field-lightweight")
        | ("autonomy", "autonomy-full") => Ok(()),
        _ => Err("Hardware-domain commands are unavailable in this edition".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compiled_identity_is_exact_and_hardware_scoped() {
        require_available()
            .expect("Universal, Lab, Field, or AGENT hardware domain must be compiled explicitly");
        assert!(matches!(edition_id(), "lab" | "field" | "autonomy"));
        if env!("DRONEDREAM_DESKTOP_EDITION_ID") == "universal" {
            assert_eq!(edition_id(), "field");
            assert_eq!(runtime_profile(), "unified-sim-lab");
        }
        if env!("DRONEDREAM_DESKTOP_EDITION_ID") == "autonomy" {
            assert_eq!(edition_id(), "autonomy");
            assert_eq!(runtime_profile(), "autonomy-full");
        }
    }
}
