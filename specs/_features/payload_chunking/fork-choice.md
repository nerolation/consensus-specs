# Payload Chunking -- Fork Choice

*Note*: This document is a work-in-progress for researchers and implementers.

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Helpers](#helpers)
  - [Modified `Store`](#modified-store)
  - [`is_chunk_available`](#is_chunk_available)
  - [`is_chunk_access_list_available`](#is_chunk_access_list_available)
  - [`is_payload_available`](#is_payload_available)
- [Execution engine interface](#execution-engine-interface)
  - [`notify_new_chunk`](#notify_new_chunk)
  - [`notify_new_chunk_access_list`](#notify_new_chunk_access_list)
  - [`finalize_chunked_payload`](#finalize_chunked_payload)
- [Handlers](#handlers)
  - [`on_chunk`](#on_chunk)
  - [`on_chunk_access_list`](#on_chunk_access_list)
  - [Modified `on_block`](#modified-on_block)

<!-- mdformat-toc end -->

## Introduction

This document specifies the fork choice modifications for payload chunking, building upon [Gloas fork choice](../../gloas/fork-choice.md).

The fork choice implements two-phase validation:
- **Phase 1**: Individual chunk validation as they arrive (streaming)
- **Phase 2**: Complete state transition verification after all chunks are received

## Custom types

| Name | SSZ equivalent | Description |
| ---- | -------------- | ----------- |
| `ChunkIndex` | `uint8` | Index of a chunk within a block (0 to MAX_CHUNKS_PER_BLOCK-1) |

## Helpers

### Modified `Store`

The `Store` is modified to track chunk and chunk access list availability.

```python
@dataclass
class Store:
    # Existing fields from Gloas
    time: uint64
    genesis_time: uint64
    finalized_checkpoint: Checkpoint
    unrealized_finalized_checkpoint: Checkpoint  
    justified_checkpoint: Checkpoint
    unrealized_justified_checkpoint: Checkpoint
    proposer_boost_root: Root
    equivocating_indices: Set[ValidatorIndex]
    blocks: Dict[Root, BeaconBlock] = field(default_factory=dict)
    block_states: Dict[Root, BeaconState] = field(default_factory=dict)
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    unrealized_justifications: Dict[Root, Checkpoint] = field(default_factory=dict)
    execution_payload_states: Dict[Root, bool] = field(default_factory=dict)  # From Gloas
    ptc_vote: Dict[Root, Vector[uint8, PTC_SIZE]] = field(default_factory=dict)  # From Gloas
    payload_withhold_boost_root: Root  # From Gloas
    payload_withhold_boost_full: bool  # From Gloas
    payload_reveal_boost_root: Root  # From Gloas
    
    # New fields for payload chunking
    chunks: Dict[Tuple[Root, ChunkIndex], ExecutionChunk] = field(default_factory=dict)
    chunk_access_lists: Dict[Tuple[Root, ChunkIndex], ChunkAccessList] = field(default_factory=dict)
    chunk_validation_status: Dict[Tuple[Root, ChunkIndex], bool] = field(default_factory=dict)  # Phase 1
    payload_chunk_availability: Dict[Root, bool] = field(default_factory=dict)
    block_state_valid: Dict[Root, bool] = field(default_factory=dict)  # Phase 2
```

### `is_chunk_available`

```python
def is_chunk_available(store: Store, block_root: Root, chunk_index: ChunkIndex) -> bool:
    return (block_root, chunk_index) in store.chunks
```

### `is_chunk_access_list_available`

```python
def is_chunk_access_list_available(store: Store, block_root: Root, cal_index: ChunkIndex) -> bool:
    return (block_root, cal_index) in store.chunk_access_lists
```

### `is_payload_available`

```python
def is_payload_available(store: Store, block_root: Root) -> bool:
    # Check cache first
    if block_root in store.payload_chunk_availability:
        return store.payload_chunk_availability[block_root]
    
    if block_root not in store.blocks:
        return False
    
    block = store.blocks[block_root]
    
    # Check all chunks are available
    num_chunks = len(block.body.chunk_roots)
    for i in range(num_chunks):
        if not is_chunk_available(store, block_root, i):
            return False
    
    # Check all chunk access lists are available  
    num_cals = len(block.body.chunk_access_list_roots)
    for i in range(num_cals):
        if not is_chunk_access_list_available(store, block_root, i):
            return False
    
    # Verify chunks match committed roots
    for i in range(num_chunks):
        chunk = store.chunks[(block_root, i)]
        if hash_tree_root(chunk) != block.body.chunk_roots[i]:
            return False
    
    # Verify chunk access lists match committed roots
    for i in range(num_cals):
        cal = store.chunk_access_lists[(block_root, i)]
        if hash_tree_root(cal) != block.body.chunk_access_list_roots[i]:
            return False
    
    # Cache the result
    store.payload_chunk_availability[block_root] = True
    return True
```

## Execution engine interface


### `notify_new_chunk`

```python
def notify_new_chunk(execution_engine: ExecutionEngine,
                     block_root: Root,
                     chunk: ExecutionChunk,
                     parent_hash: Hash32) -> bool:
    """Phase 1: Validate individual chunk as it arrives"""
    return execution_engine.engine_newChunk(
        chunk=chunk,
        parent_hash=parent_hash
    )
```

### `notify_new_chunk_access_list`

```python
def notify_new_chunk_access_list(execution_engine: ExecutionEngine,
                                 block_hash: Hash32,
                                 index: uint8,
                                 chunk_access_list: ChunkAccessList) -> bool:
    """Provide CAL to execution engine for chunk processing"""
    return execution_engine.engine_newChunkAccessList(
        block_hash=block_hash,
        index=index,
        cal=chunk_access_list
    )
```

### `finalize_chunked_payload`

```python
def finalize_chunked_payload(execution_engine: ExecutionEngine,
                            block_hash: Hash32,
                            expected_chunks: List[ChunkIndex],
                            state_root: Hash32) -> bool:
    """Phase 2: Verify complete state transition after all chunks received
    
    This verifies:
    - State continuity between chunks
    - Final state root matches the block header commitment
    - All chunks executed successfully
    """
    payload_status = execution_engine.engine_finalizeChunkedPayload(
        block_hash=block_hash,
        expected_chunks=expected_chunks,
        state_root=state_root
    )
    return payload_status.status == "VALID"
```

## Handlers

### `on_chunk`

```python
def on_chunk(store: Store, chunk_sidecar: ExecutionChunkSidecar) -> None:
    # Verify the chunk sidecar signature and inclusion proof
    assert verify_chunk_inclusion_proof(chunk_sidecar)
    
    chunk = chunk_sidecar.chunk
    chunk_index = chunk.chunk_header.index
    
    # Verify chunk properties
    assert chunk.chunk_header.gas_used <= CHUNK_GAS_LIMIT
    
    # Non-terminal chunks must meet minimum fill
    if chunk_index < len(store.blocks[block_root].body.chunk_roots) - 1:
        assert chunk.chunk_header.gas_used >= CHUNK_GAS_LIMIT * MIN_CHUNK_FILL_RATIO
    
    block_root = chunk_sidecar.chunk_signature.message.body_root
    parent_root = chunk_sidecar.chunk_signature.message.parent_root
    
    # Store the chunk
    store.chunks[(block_root, chunk_index)] = chunk
    
    # Phase 1: Validate chunk independently
    parent_block = store.blocks[parent_root]
    is_valid = notify_new_chunk(
        execution_engine,
        block_root,
        chunk,
        parent_block.body.execution_payload_header.block_hash
    )
    
    if is_valid:
        store.chunk_validation_status[(block_root, chunk_index)] = True
    
    # Check if all chunks and CALs are now available
    if block_root in store.blocks:
        check_and_finalize_block(store, block_root)
```

### `on_chunk_access_list`

```python
def on_chunk_access_list(store: Store, cal_sidecar: ChunkAccessListSidecar) -> None:
    # Verify the CAL sidecar signature and inclusion proof
    assert verify_chunk_access_list_inclusion_proof(cal_sidecar)
    
    block_root = cal_sidecar.cal_signature.message.body_root
    
    # Determine CAL index from its position in the block
    block = store.blocks[block_root]
    cal_index = None
    for i, root in enumerate(block.body.chunk_access_list_roots):
        if hash_tree_root(cal_sidecar.chunk_access_list) == root:
            cal_index = i
            break
    assert cal_index is not None
    
    # Store the chunk access list
    store.chunk_access_lists[(block_root, cal_index)] = cal_sidecar.chunk_access_list
    
    # Provide to execution engine
    block = store.blocks[block_root]
    notify_new_chunk_access_list(
        execution_engine,
        block.body.execution_payload_header.block_hash,
        cal_index,
        cal_sidecar.chunk_access_list
    )
    
    # Check if all chunks and CALs are now available
    if block_root in store.blocks:
        check_and_finalize_block(store, block_root)
```

### Modified `on_block`

The `on_block` handler is modified to account for chunked payloads.

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    block = signed_block.message
    block_root = hash_tree_root(block)
    
    # Validate block
    assert block.parent_root in store.block_states
    assert block.slot > store.blocks[block.parent_root].slot
    
    # Verify chunk roots are present
    assert len(block.body.chunk_roots) > 0
    assert len(block.body.chunk_roots) <= MAX_CHUNKS_PER_BLOCK
    assert len(block.body.chunk_roots) == len(block.body.chunk_access_list_roots)
    
    # Store the block
    store.blocks[block_root] = block
    
    
    if is_payload_available(store, block_root):
        process_block_for_fork_choice(store, block_root)
```

```python
def check_and_finalize_block(store: Store, block_root: Root) -> None:
    """Check if block is ready for Phase 2 validation"""
    block = store.blocks[block_root]
    num_chunks = len(block.body.chunk_roots)
    
    # Check Phase 1: All chunks individually validated
    all_chunks_validated = all(
        store.chunk_validation_status.get((block_root, i), False)
        for i in range(num_chunks)
    )
    
    # Check all CALs available
    all_cals_available = all(
        is_chunk_access_list_available(store, block_root, i)
        for i in range(len(block.body.chunk_access_list_roots))
    )
    
    if all_chunks_validated and all_cals_available:
        store.payload_chunk_availability[block_root] = True
        
        # Phase 2: Verify complete state transition
        finalize_block_validation(store, block_root)
```

```python
def finalize_block_validation(store: Store, block_root: Root) -> None:
    """Phase 2: Verify complete state transition"""
    block = store.blocks[block_root]
    
    # Get expected chunks for validation
    expected_chunks = list(range(len(block.body.chunk_roots)))
    
    # Phase 2: Verify final state matches header commitment
    is_valid = finalize_chunked_payload(
        execution_engine,
        block.body.execution_payload_header.block_hash,
        expected_chunks,
        block.body.execution_payload_header.state_root
    )
    
    if is_valid:
        store.block_state_valid[block_root] = True
        store.execution_payload_states[block_root] = True
        
        # Process block for fork choice if not already done
        if block_root not in store.block_states:
            process_block_for_fork_choice(store, block_root)
    else:
        # Block failed Phase 2 validation
        del store.blocks[block_root]
        if block_root in store.payload_chunk_availability:
            del store.payload_chunk_availability[block_root]
        # Clean up chunk data
        for i in range(len(block.body.chunk_roots)):
            if (block_root, i) in store.chunks:
                del store.chunks[(block_root, i)]
            if (block_root, i) in store.chunk_access_lists:
                del store.chunk_access_lists[(block_root, i)]
```

```python
def process_block_for_fork_choice(store: Store, block_root: Root) -> None:
    """Process block after successful two-phase validation"""
    block = store.blocks[block_root]
    
    state = store.block_states[block.parent_root].copy()
    state_transition(state, signed_block, validate_result=False)
    store.block_states[block_root] = state
```

```python
def is_block_valid_for_attestation(store: Store, block_root: Root) -> bool:
    """Check if block has passed both validation phases"""
    # Must have all chunks and CALs
    if not store.payload_chunk_availability.get(block_root, False):
        return False
    
    # Must have passed Phase 2 validation
    if not store.block_state_valid.get(block_root, False):
        return False
    
    return True
```