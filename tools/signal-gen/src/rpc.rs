//! TCP RPC server for JSON command interface.
//!
//! Listens on a localhost TCP port (default 127.0.0.1:4001) and accepts
//! newline-delimited JSON commands. Multiple simultaneous clients are
//! supported. State broadcasts are sent to all connected clients.
//!
//! Line length is capped at 4096 bytes per SEC-D037-03.
