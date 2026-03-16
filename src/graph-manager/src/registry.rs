//! PipeWire registry listener — detects node/port/link appear/disappear
//! events and updates the GraphState, then triggers reconciliation.
//!
//! The registry listener is the push-based graph awareness mechanism
//! (US-059 AC: "detects node appearance and disappearance within 100ms,
//! without polling"). PipeWire's registry API delivers events as globals
//! are added and removed — no polling needed.
//!
//! After every graph state mutation, the reconciliation engine runs
//! synchronously on the PW main loop thread. This produces a list of
//! link actions (create/destroy) that the caller must apply.
//!
//! ## Thread model
//!
//! Registry callbacks run on the PW main loop thread (single-threaded).
//! GraphState is accessed only from this thread. RPC snapshots are
//! delivered via a channel, not direct access.
//!
//! ## Design
//!
//! We track three PW object types:
//! - **Node** (ObjectType::Node): application and device nodes
//! - **Port** (ObjectType::Port): per-channel ports on nodes
//! - **Link** (ObjectType::Link): connections between ports
//!
//! On `global` events, we extract properties and insert into GraphState.
//! On `global_remove`, we remove by ID and log the event.
//! After each mutation, `reconcile()` runs and link actions are logged.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use crate::graph::{GraphState, TrackedLink, TrackedNode, TrackedPort};
use crate::reconcile::{self, LinkAction};
use crate::routing::{Mode, RoutingTable};

/// Log reconciliation actions. Actual PW link creation/destruction will
/// be added when the PW link API integration lands (future task).
fn log_actions(actions: &[LinkAction]) {
    if actions.is_empty() {
        return;
    }
    log::info!("Reconciliation produced {} action(s):", actions.len());
    for action in actions {
        match action {
            LinkAction::Create { description, .. } => {
                log::info!("  CREATE: {}", description);
            }
            LinkAction::Destroy { link_id, description } => {
                log::info!("  DESTROY id={}: {}", link_id, description);
            }
        }
    }
}

/// Run reconciliation against the current graph state and log actions.
///
/// Called after every graph mutation. The reconcile function is pure —
/// it reads state and returns actions. Actual PW link API calls will
/// be wired in a future task; for now we log the actions.
fn run_reconcile(
    graph: &GraphState,
    table: &RoutingTable,
    mode: Mode,
) {
    let actions = reconcile::reconcile(graph, table, mode);
    log_actions(&actions);
    // TODO (GM-4): Apply link actions via PW API:
    //   - Create: core.create_object::<pw::link::Link>("link-factory", &props)
    //   - Destroy: core.destroy_object(proxy) or registry.destroy_global(id)
    //   - Store proxies in HashMap<(u32, u32), pw::link::Link>
}

/// Register the PW registry listener that populates GraphState from
/// registry events and triggers reconciliation after each mutation.
///
/// Returns the registry and listener objects. Both must be kept alive
/// for the duration of the PW main loop (drop order matters).
///
/// # Arguments
/// * `core` - PW core connection.
/// * `graph` - Shared GraphState, wrapped in Rc<RefCell<>> for
///   single-threaded sharing between the two closures.
/// * `table` - Routing table (all modes and their desired links).
/// * `mode` - Shared current operating mode, wrapped in Rc<RefCell<>>
///   so that RPC mode transitions update the value for the next
///   reconciliation cycle.
pub fn register_graph_listener(
    core: &pipewire::core::Core,
    graph: Rc<RefCell<GraphState>>,
    table: Rc<RoutingTable>,
    mode: Rc<RefCell<Mode>>,
) -> (pipewire::registry::Registry, Box<dyn std::any::Any>) {
    let registry = core
        .get_registry()
        .expect("Failed to get PipeWire registry");

    let graph_add = graph.clone();
    let table_add = table.clone();
    let mode_add = mode.clone();
    let graph_remove = graph;
    let table_remove = table;
    let mode_remove = mode;

    let listener = registry
        .add_listener_local()
        .global(move |global| {
            let mut g = graph_add.borrow_mut();
            let mut mutated = false;

            if global.type_ == pipewire::types::ObjectType::Node {
                if let Some(props) = global.props {
                    let node_name = props.get("node.name").unwrap_or("").to_string();
                    let media_class = props.get("media.class").unwrap_or("").to_string();

                    let mut properties = HashMap::new();
                    for key in &[
                        "node.name",
                        "node.description",
                        "media.class",
                        "media.type",
                        "media.category",
                        "media.role",
                        "node.group",
                        "application.name",
                        "client.api",
                    ] {
                        if let Some(val) = props.get(key) {
                            properties.insert(key.to_string(), val.to_string());
                        }
                    }

                    g.add_node(TrackedNode {
                        id: global.id,
                        name: node_name,
                        media_class,
                        properties,
                    });
                    mutated = true;
                }
            } else if global.type_ == pipewire::types::ObjectType::Port {
                if let Some(props) = global.props {
                    let node_id = props
                        .get("node.id")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let port_name = props.get("port.name").unwrap_or("").to_string();
                    let direction = props.get("port.direction").unwrap_or("").to_string();

                    let mut properties = HashMap::new();
                    for key in &[
                        "port.name",
                        "port.alias",
                        "port.direction",
                        "port.id",
                        "node.id",
                        "format.dsp",
                        "audio.channel",
                    ] {
                        if let Some(val) = props.get(key) {
                            properties.insert(key.to_string(), val.to_string());
                        }
                    }

                    g.add_port(TrackedPort {
                        id: global.id,
                        node_id,
                        name: port_name,
                        direction,
                        properties,
                    });
                    mutated = true;
                }
            } else if global.type_ == pipewire::types::ObjectType::Link {
                if let Some(props) = global.props {
                    let output_port = props
                        .get("link.output.port")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let input_port = props
                        .get("link.input.port")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let output_node = props
                        .get("link.output.node")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);
                    let input_node = props
                        .get("link.input.node")
                        .and_then(|s| s.parse::<u32>().ok())
                        .unwrap_or(0);

                    g.add_link(TrackedLink {
                        id: global.id,
                        output_port,
                        input_port,
                        output_node,
                        input_node,
                    });
                    mutated = true;
                }
            }

            // Trigger reconciliation after every graph mutation.
            if mutated {
                let current_mode = *mode_add.borrow();
                run_reconcile(&g, &table_add, current_mode);
            }
        })
        .global_remove(move |id| {
            let mut g = graph_remove.borrow_mut();

            // We don't know the object type from global_remove, so try
            // removing from all three collections. At most one will match.
            let removed = if g.remove_link(id).is_some() {
                true
            } else if g.remove_port(id).is_some() {
                true
            } else if g.remove_node(id).is_some() {
                true
            } else {
                // ID not tracked — this is normal for object types we don't
                // track (Client, Module, Factory, etc).
                log::trace!("global_remove for untracked id={}", id);
                false
            };

            // Trigger reconciliation after every graph mutation.
            if removed {
                let current_mode = *mode_remove.borrow();
                run_reconcile(&g, &table_remove, current_mode);
            }
        })
        .register();

    (registry, Box::new(listener))
}
