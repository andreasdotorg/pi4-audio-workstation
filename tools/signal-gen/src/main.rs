//! pi4audio-signal-gen -- RT signal generator for measurement and test tooling.
//!
//! Maintains an always-on PipeWire playback stream (targeting the loopback sink
//! that feeds CamillaDSP) and a capture stream (targeting the UMIK-1). Signal
//! content is controlled via a JSON-over-TCP RPC interface without ever closing
//! or reopening the audio streams.
//!
//! This eliminates TK-224's root cause: WirePlumber routing races caused by
//! per-burst stream opening in the Python measurement pipeline.

mod capture;
mod command;
mod generator;
mod ramp;
mod registry;
mod rpc;
mod safety;

use std::process;

use clap::Parser;
use log::error;

/// RT signal generator for Pi audio workstation measurement and test tooling.
#[derive(Parser, Debug)]
#[command(name = "pi4audio-signal-gen", version)]
struct Args {
    /// PipeWire playback target node name.
    #[arg(long, default_value = "loopback-8ch-sink")]
    target: String,

    /// PipeWire capture target node name (UMIK-1).
    #[arg(long, default_value = "UMIK-1")]
    capture_target: String,

    /// Number of output channels.
    #[arg(long, default_value_t = 8)]
    channels: u32,

    /// Sample rate in Hz.
    #[arg(long, default_value_t = 48000)]
    rate: u32,

    /// RPC listen address (tcp:HOST:PORT).
    #[arg(long, default_value = "tcp:127.0.0.1:4001")]
    listen: String,

    /// Hard output level cap in dBFS (immutable after startup).
    #[arg(long, default_value_t = -20.0)]
    max_level_dbfs: f64,

    /// Fade ramp duration in milliseconds.
    #[arg(long, default_value_t = 20)]
    ramp_ms: u32,

    /// Capture ring buffer duration in seconds.
    #[arg(long, default_value_t = 30)]
    capture_buffer_secs: u32,

    /// Device name pattern to watch for hot-plug events.
    #[arg(long, default_value = "UMIK-1")]
    device_watch: String,
}

/// Validate safety-critical arguments before entering the main loop.
///
/// SEC-D037-01: Reject non-loopback listen addresses.
/// SEC-D037-04: Reject max_level_dbfs outside [-120.0, -0.5].
fn validate_args(args: &Args) -> Result<(), String> {
    // SEC-D037-01: Loopback-only binding
    let addr = args.listen.strip_prefix("tcp:").unwrap_or(&args.listen);
    let host = addr.rsplit_once(':').map(|(h, _)| h).unwrap_or(addr);
    match host {
        "127.0.0.1" | "::1" | "localhost" => {}
        _ => {
            return Err(format!(
                "Error: --listen address must be loopback \
                 (127.0.0.1, ::1, or localhost). \
                 Binding to non-loopback addresses is prohibited. Got: {host}"
            ))
        }
    }

    // SEC-D037-04: Level cap ceiling
    if args.max_level_dbfs > -0.5 {
        return Err(format!(
            "Error: --max-level-dbfs must be <= -0.5 \
             (D-009 absolute ceiling). Got: {}",
            args.max_level_dbfs
        ));
    }
    if args.max_level_dbfs < -120.0 {
        return Err(format!(
            "Error: --max-level-dbfs must be >= -120.0. Got: {}",
            args.max_level_dbfs
        ));
    }

    Ok(())
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let args = Args::parse();

    if let Err(msg) = validate_args(&args) {
        error!("{}", msg);
        process::exit(1);
    }

    log::info!(
        "pi4audio-signal-gen starting: target={}, capture_target={}, \
         channels={}, rate={}, listen={}, max_level_dbfs={}, ramp_ms={}",
        args.target,
        args.capture_target,
        args.channels,
        args.rate,
        args.listen,
        args.max_level_dbfs,
        args.ramp_ms,
    );

    // TODO(SG-2+): PipeWire stream setup, RPC server, signal processing loop.
    // For now, the scaffold validates args and exits cleanly.
    log::info!("Scaffold complete — PipeWire streams not yet implemented.");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validate_loopback_ipv4_accepted() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:127.0.0.1:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }

    #[test]
    fn validate_loopback_ipv6_accepted() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:::1:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }

    #[test]
    fn validate_loopback_localhost_accepted() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:localhost:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }

    #[test]
    fn validate_non_loopback_rejected() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:0.0.0.0:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        let err = validate_args(&args).unwrap_err();
        assert!(err.contains("loopback"), "Error should mention loopback: {err}");
    }

    #[test]
    fn validate_external_ip_rejected() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:192.168.1.1:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_err());
    }

    #[test]
    fn validate_max_level_at_ceiling_accepted() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:127.0.0.1:4001".into(),
            max_level_dbfs: -0.5,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }

    #[test]
    fn validate_max_level_above_ceiling_rejected() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:127.0.0.1:4001".into(),
            max_level_dbfs: 0.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        let err = validate_args(&args).unwrap_err();
        assert!(err.contains("-0.5"), "Error should mention -0.5 ceiling: {err}");
    }

    #[test]
    fn validate_max_level_below_floor_rejected() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:127.0.0.1:4001".into(),
            max_level_dbfs: -130.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        let err = validate_args(&args).unwrap_err();
        assert!(err.contains("-120.0"), "Error should mention -120.0 floor: {err}");
    }

    #[test]
    fn validate_default_level_accepted() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "tcp:127.0.0.1:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }

    #[test]
    fn validate_listen_without_tcp_prefix() {
        let args = Args {
            target: "loopback-8ch-sink".into(),
            capture_target: "UMIK-1".into(),
            channels: 8,
            rate: 48000,
            listen: "127.0.0.1:4001".into(),
            max_level_dbfs: -20.0,
            ramp_ms: 20,
            capture_buffer_secs: 30,
            device_watch: "UMIK-1".into(),
        };
        assert!(validate_args(&args).is_ok());
    }
}
