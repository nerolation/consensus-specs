# EIP-8146 -- Fork Choice

*Note*: This document is a work-in-progress for researchers and implementers.

## Table of contents

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Protocols](#protocols)
  - [`ExecutionEngine`](#executionengine)
    - [New `notify_block_access_list`](#new-notify_block_access_list)
- [Helpers](#helpers)
  - [Modified `Store`](#modified-store)
  - [Modified `get_forkchoice_store`](#modified-get_forkchoice_store)
- [Handlers](#handlers)
  - [Modified `on_block`](#modified-on_block)
  - [New `on_block_access_list_sidecar`](#new-on_block_access_list_sidecar)
  - [Modified `on_execution_payload_envelope`](#modified-on_execution_payload_envelope)
  - [Modified `on_payload_attestation_message`](#modified-on_payload_attestation_message)

<!-- mdformat-toc end -->

## Introduction

Fork-choice changes for EIP-8146. Built upon
[Gloas](../../gloas/fork-choice.md).

## Protocols

### `ExecutionEngine`

#### New `notify_block_access_list`

*Note*: Delivers the BAL to the EL ahead of the execution payload envelope.
The EL stores the bytes keyed by `block_hash` and MAY begin prefetching the
referenced state. When the corresponding `engine_newPayloadV5` arrives, the
EL pairs them by `block_hash`. The CL only calls this method for bytes that
have already passed the `keccak256` check against `bid.block_access_list_hash`.

```python
def notify_block_access_list(
    self: ExecutionEngine,
    block_hash: Hash32,
    block_access_list: BlockAccessList,
) -> None: ...
```

## Helpers

### Modified `Store`

*Note*: `Store` is modified to track received BAL sidecars and PTC votes on
their availability.

```python
@dataclass
class Store:
    time: uint64
    genesis_time: uint64
    justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    unrealized_justified_checkpoint: Checkpoint
    unrealized_finalized_checkpoint: Checkpoint
    proposer_boost_root: Root
    equivocating_indices: Set[ValidatorIndex]
    blocks: Dict[Root, BeaconBlock] = field(default_factory=dict)
    block_states: Dict[Root, BeaconState] = field(default_factory=dict)
    block_timeliness: Dict[Root, list[boolean]] = field(default_factory=dict)
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    latest_messages: Dict[ValidatorIndex, LatestMessage] = field(default_factory=dict)
    unrealized_justifications: Dict[Root, Checkpoint] = field(default_factory=dict)
    payloads: Dict[Root, ExecutionPayloadEnvelope] = field(default_factory=dict)
    payload_timeliness_vote: Dict[Root, list[Optional[boolean]]] = field(default_factory=dict)
    payload_data_availability_vote: Dict[Root, list[Optional[boolean]]] = field(
        default_factory=dict
    )
    # [New in EIP8146]
    block_access_lists: Dict[Root, BlockAccessList] = field(default_factory=dict)
    # [New in EIP8146]
    block_access_list_availability_vote: Dict[Root, list[Optional[boolean]]] = field(
        default_factory=dict
    )
```

### Modified `get_forkchoice_store`

```python
def get_forkchoice_store(anchor_state: BeaconState, anchor_block: BeaconBlock) -> Store:
    assert anchor_block.state_root == hash_tree_root(anchor_state)
    anchor_root = hash_tree_root(anchor_block)
    anchor_epoch = get_current_epoch(anchor_state)
    justified_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    finalized_checkpoint = Checkpoint(epoch=anchor_epoch, root=anchor_root)
    proposer_boost_root = Root()
    return Store(
        time=uint64(anchor_state.genesis_time + SLOT_DURATION_MS * anchor_state.slot // 1000),
        genesis_time=anchor_state.genesis_time,
        justified_checkpoint=justified_checkpoint,
        finalized_checkpoint=finalized_checkpoint,
        unrealized_justified_checkpoint=justified_checkpoint,
        unrealized_finalized_checkpoint=finalized_checkpoint,
        proposer_boost_root=proposer_boost_root,
        equivocating_indices=set(),
        blocks={anchor_root: copy(anchor_block)},
        block_states={anchor_root: copy(anchor_state)},
        block_timeliness={anchor_root: [True, True]},
        checkpoint_states={justified_checkpoint: copy(anchor_state)},
        unrealized_justifications={anchor_root: justified_checkpoint},
        payloads={},
        payload_timeliness_vote={},
        payload_data_availability_vote={},
        # [New in EIP8146]
        block_access_lists={},
        # [New in EIP8146]
        block_access_list_availability_vote={},
    )
```

## Handlers

### Modified `on_block`

*Note*: One line is added to initialise the BAL availability vote tracker.

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    """
    Run ``on_block`` upon receiving a new block.
    """
    block = signed_block.message
    assert block.parent_root in store.block_states
    if is_parent_node_full(store, block):
        assert is_payload_verified(store, block.parent_root)
    current_slot = get_current_slot(store)
    assert current_slot >= block.slot
    finalized_slot = compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
    assert block.slot > finalized_slot
    finalized_checkpoint_block = get_checkpoint_block(
        store,
        block.parent_root,
        store.finalized_checkpoint.epoch,
    )
    assert store.finalized_checkpoint.root == finalized_checkpoint_block

    state = copy(store.block_states[block.parent_root])
    block_root = hash_tree_root(block)
    state_transition(state, signed_block, True)

    store.blocks[block_root] = block
    store.block_states[block_root] = state
    store.payload_timeliness_vote[block_root] = [None] * PTC_SIZE
    store.payload_data_availability_vote[block_root] = [None] * PTC_SIZE
    # [New in EIP8146]
    store.block_access_list_availability_vote[block_root] = [None] * PTC_SIZE

    notify_ptc_messages(store, state, block.body.payload_attestations)

    record_block_timeliness(store, block_root)
    update_proposer_boost_root(store, block_root)

    update_checkpoints(store, state.current_justified_checkpoint, state.finalized_checkpoint)

    compute_pulled_up_tip(store, block_root)
```

### New `on_block_access_list_sidecar`

*Note*: Called when a `BlockAccessListSidecar` passes gossip or req/resp
validation. Verifies the bid commitment over the opaque BAL bytes, stores
the BAL, and delivers it to the EL.

```python
def on_block_access_list_sidecar(store: Store, sidecar: BlockAccessListSidecar) -> None:
    # The corresponding beacon block must be known
    assert sidecar.beacon_block_root in store.blocks
    block = store.blocks[sidecar.beacon_block_root]
    bid = block.body.signed_execution_payload_bid.message

    # Slot consistency
    assert sidecar.slot == block.slot

    # BAL matches the bid commitment (CL operates on opaque bytes; no RLP)
    assert keccak256(sidecar.block_access_list) == bid.block_access_list_hash

    # Store BAL
    store.block_access_lists[sidecar.beacon_block_root] = sidecar.block_access_list

    # Deliver to the EL for early prefetching
    EXECUTION_ENGINE.notify_block_access_list(
        block_hash=bid.block_hash,
        block_access_list=sidecar.block_access_list,
    )
```

### Modified `on_execution_payload_envelope`

*Note*: A local BAL availability assertion is added. The EL already holds
the BAL (delivered via `notify_block_access_list` when the sidecar arrived);
`verify_execution_payload_envelope` is unchanged.

```python
def on_execution_payload_envelope(
    store: Store, signed_envelope: SignedExecutionPayloadEnvelope
) -> None:
    """
    Run ``on_execution_payload_envelope`` upon receiving a new execution payload envelope.
    """
    envelope = signed_envelope.message
    assert envelope.beacon_block_root in store.block_states

    assert is_data_available(envelope.beacon_block_root)

    # [New in EIP8146]
    assert envelope.beacon_block_root in store.block_access_lists

    state = store.block_states[envelope.beacon_block_root]

    verify_execution_payload_envelope(state, signed_envelope, EXECUTION_ENGINE)

    store.payloads[envelope.beacon_block_root] = envelope
```

### Modified `on_payload_attestation_message`

*Note*: One line is added inside the existing `ptc_indices` loop to record
the new BAL availability vote.

```python
def on_payload_attestation_message(
    store: Store, ptc_message: PayloadAttestationMessage, is_from_block: bool = False
) -> None:
    """
    Run ``on_payload_attestation_message`` upon receiving a new ``ptc_message`` from
    either within a block or directly on the wire.
    """
    data = ptc_message.data

    assert data.beacon_block_root in store.block_states
    state = store.block_states[data.beacon_block_root]

    if data.slot != state.slot:
        return

    ptc_indices = []
    ptc = get_ptc(state, data.slot)
    for ptc_index, validator_index in enumerate(ptc):
        if validator_index == ptc_message.validator_index:
            ptc_indices.append(ptc_index)

    assert len(ptc_indices) > 0

    if not is_from_block:
        assert data.slot == get_current_slot(store)
        assert is_valid_indexed_payload_attestation(
            state,
            IndexedPayloadAttestation(
                attesting_indices=[ptc_message.validator_index],
                data=data,
                signature=ptc_message.signature,
            ),
        )

    payload_timeliness_vote = store.payload_timeliness_vote[data.beacon_block_root]
    payload_data_availability_vote = store.payload_data_availability_vote[data.beacon_block_root]
    # [New in EIP8146]
    block_access_list_availability_vote = store.block_access_list_availability_vote[
        data.beacon_block_root
    ]
    for ptc_index in ptc_indices:
        payload_timeliness_vote[ptc_index] = data.payload_present
        payload_data_availability_vote[ptc_index] = data.blob_data_available
        # [New in EIP8146]
        block_access_list_availability_vote[ptc_index] = data.block_access_list_present
```
