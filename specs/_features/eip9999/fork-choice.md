# EIP-9999 -- Fork Choice

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This specification extends the Gloas fork choice to support streaming chunk execution with CAL-based state reconstruction.

## Custom types

| Name | SSZ equivalent | Description |
| - | - | - |
| `ChunkStatus` | `uint8` | Status of chunk execution |

## Constants

| Name | Value | Description |
| - | - | - |
| `CHUNK_STATUS_PENDING` | `ChunkStatus(0)` | Not yet received |
| `CHUNK_STATUS_WAITING` | `ChunkStatus(1)` | Waiting for CALs |
| `CHUNK_STATUS_EXECUTING` | `ChunkStatus(2)` | Currently executing |
| `CHUNK_STATUS_VALID` | `ChunkStatus(3)` | Successfully executed |
| `CHUNK_STATUS_INVALID` | `ChunkStatus(4)` | Execution failed |

## Containers

### Modified `Store`

```python
@dataclass
class Store(object):
    # Existing Gloas fields unchanged
    # ...
    
    # Chunk and CAL storage [New in EIP9999]
    chunks: Dict[Tuple[Root, uint8], ExecutionChunk] = field(default_factory=dict)
    chunk_hashes: Dict[Tuple[Root, uint8], Hash32] = field(default_factory=dict)
    chunk_access_lists: Dict[Tuple[Root, uint8], ChunkAccessList] = field(default_factory=dict)
    chunk_status: Dict[Tuple[Root, uint8], ChunkStatus] = field(default_factory=dict)
    
    # Orphan chunk storage (before block arrives) [New in EIP9999]
    orphan_chunks: Dict[Tuple[Slot, ValidatorIndex, uint8], ExecutionChunk] = field(default_factory=dict)
    orphan_cals: Dict[Tuple[Slot, ValidatorIndex, uint8], ChunkAccessList] = field(default_factory=dict)
    orphan_chunk_status: Dict[Tuple[Slot, ValidatorIndex, uint8], ChunkStatus] = field(default_factory=dict)
    
    # Block finalization tracking
    block_finalized: Dict[Root, bool] = field(default_factory=dict)
```

## Streaming Execution

Chunks execute in sequence as CALs (state diffs) become available:
- Chunk 0 executes on parent state → generates CAL 0
- Chunk N applies CALs 0..N-1 to parent state → generates CAL N
- Hash chain validated at finalization

### `on_block`

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    """
    Process beacon block and associate any orphan chunks.
    """
    block = signed_block.message
    block_root = hash_tree_root(block)
    slot = block.slot
    proposer = block.proposer_index
    
    # Existing Gloas validation
    # ...
    
    # Process chunks [New in EIP9999]
    if has_chunks(block):
        bid = block.body.signed_execution_payload_bid.message
        
        # Check for orphan chunks that belong to this block
        for i in range(len(bid.chunk_roots)):
            orphan_key = (slot, proposer, i)
            
            # Move orphan chunk to confirmed storage if it matches commitment
            if orphan_key in store.orphan_chunks:
                chunk = store.orphan_chunks[orphan_key]
                if validate_chunk_commitment(chunk, i, bid):
                    store.chunks[(block_root, i)] = chunk
                    store.chunk_hashes[(block_root, i)] = compute_chunk_hash(chunk)
                    store.chunk_status[(block_root, i)] = store.orphan_chunk_status.get(
                        orphan_key, CHUNK_STATUS_PENDING
                    )
                    del store.orphan_chunks[orphan_key]
                    if orphan_key in store.orphan_chunk_status:
                        del store.orphan_chunk_status[orphan_key]
            
            # Move orphan CAL to confirmed storage if it matches commitment
            if orphan_key in store.orphan_cals:
                cal = store.orphan_cals[orphan_key]
                if validate_cal_commitment(cal, i, bid):
                    store.chunk_access_lists[(block_root, i)] = cal
                    del store.orphan_cals[orphan_key]
                    
                    # Try to execute chunks now that we have confirmed CALs
                    for j in range(i + 1, len(bid.chunk_roots)):
                        if store.chunk_status.get((block_root, j)) == CHUNK_STATUS_WAITING:
                            try_execute_chunk(store, block_root, j)
            
            # Set status for any missing chunks
            if (block_root, i) not in store.chunk_status:
                store.chunk_status[(block_root, i)] = CHUNK_STATUS_PENDING
        
        store.block_finalized[block_root] = False
        
        # Check if we can finalize immediately
        check_block_finalization(store, block_root)
```

### `on_execution_chunk_sidecar`

```python
def on_execution_chunk_sidecar(store: Store, sidecar: ExecutionChunkSidecar) -> None:
    """
    Handle chunk arrival - can process before beacon block.
    """
    slot = sidecar.slot
    proposer = sidecar.proposer_index
    chunk_index = sidecar.chunk_index
    chunk = sidecar.chunk
    
    # Validate sidecar structure
    assert validate_chunk_sidecar(store, sidecar)
    
    # Check if we have the beacon block yet
    block_root = get_block_root_for_slot_proposer(store, slot, proposer)
    
    if block_root is not None:
        # Block exists - validate commitment and store normally
        block = store.blocks[block_root]
        bid = block.body.signed_execution_payload_bid.message
        
        if validate_chunk_commitment(chunk, chunk_index, bid):
            store.chunks[(block_root, chunk_index)] = chunk
            store.chunk_hashes[(block_root, chunk_index)] = compute_chunk_hash(chunk)
            
            # Try to execute if prerequisites met
            if chunk_index == 0:
                execute_chunk_with_cals(store, block_root, 0, [])
            else:
                store.chunk_status[(block_root, chunk_index)] = CHUNK_STATUS_WAITING
                try_execute_chunk(store, block_root, chunk_index)
    else:
        # Block doesn't exist yet - store as orphan
        orphan_key = (slot, proposer, chunk_index)
        store.orphan_chunks[orphan_key] = chunk
        
        # Try to execute orphan chunk if prerequisites available
        if chunk_index == 0:
            execute_orphan_chunk_with_cals(store, slot, proposer, 0, [])
        else:
            store.orphan_chunk_status[orphan_key] = CHUNK_STATUS_WAITING
            try_execute_orphan_chunk(store, slot, proposer, chunk_index)
```

### `on_chunk_access_list_sidecar`

```python
def on_chunk_access_list_sidecar(store: Store, sidecar: ChunkAccessListSidecar) -> None:
    """
    Handle CAL arrival - can process before beacon block.
    """
    slot = sidecar.slot
    proposer = sidecar.proposer_index
    cal_index = sidecar.chunk_index
    cal = sidecar.chunk_access_list
    
    # Validate sidecar
    assert validate_cal_sidecar(store, sidecar)
    
    # Check if we have the beacon block yet
    block_root = get_block_root_for_slot_proposer(store, slot, proposer)
    
    if block_root is not None:
        # Block exists - validate commitment and store normally
        block = store.blocks[block_root]
        bid = block.body.signed_execution_payload_bid.message
        
        if validate_cal_commitment(cal, cal_index, bid):
            store.chunk_access_lists[(block_root, cal_index)] = cal
            
            # Try to execute chunks waiting for this CAL
            for i in range(cal_index + 1, MAX_CHUNKS_PER_BLOCK):
                if store.chunk_status.get((block_root, i)) == CHUNK_STATUS_WAITING:
                    try_execute_chunk(store, block_root, i)
    else:
        # Block doesn't exist yet - store as orphan
        orphan_key = (slot, proposer, cal_index)
        store.orphan_cals[orphan_key] = cal
        
        # Try to execute orphan chunks waiting for this CAL
        for i in range(cal_index + 1, MAX_CHUNKS_PER_BLOCK):
            if store.orphan_chunk_status.get((slot, proposer, i)) == CHUNK_STATUS_WAITING:
                try_execute_orphan_chunk(store, slot, proposer, i)
```

### `try_execute_chunk`

```python
def try_execute_chunk(store: Store, block_root: Root, chunk_index: uint8) -> None:
    """
    Execute chunk if all required CALs are available.
    """
    # Check chunk is available
    if (block_root, chunk_index) not in store.chunks:
        return
    
    # Gather required CALs (0 to chunk_index-1)
    required_cals = []
    for i in range(chunk_index):
        if (block_root, i) not in store.chunk_access_lists:
            return  # CAL not available yet
        required_cals.append(store.chunk_access_lists[(block_root, i)])
    
    # All prerequisites available - execute
    execute_chunk_with_cals(store, block_root, chunk_index, required_cals)
```

### `execute_chunk_with_cals`

```python
def execute_chunk_with_cals(
    store: Store,
    block_root: Root,
    chunk_index: uint8,
    required_cals: List[ChunkAccessList]
) -> None:
    """
    Execute chunk using CALs to reconstruct pre-state.
    """
    chunk = store.chunks[(block_root, chunk_index)]
    
    # Mark as executing
    store.chunk_status[(block_root, chunk_index)] = CHUNK_STATUS_EXECUTING
    
    # Execute chunk with CALs for state reconstruction
    # The EL applies CALs to parent state to get chunk's pre-state
    result = engine_execute_chunk_with_cals(
        beacon_block_root=block_root,
        chunk=chunk,
        required_cals=required_cals  # CALs 0..chunk_index-1
    )
    
    if result.status == "VALID":
        store.chunk_status[(block_root, chunk_index)] = CHUNK_STATUS_VALID
        
        # Store the generated CAL for this chunk
        # This enables execution of the next chunk (streaming cascade)
        store.chunk_access_lists[(block_root, chunk_index)] = result.chunk_access_list
        
        # Try to execute next chunk if available
        if chunk_index + 1 < MAX_CHUNKS_PER_BLOCK:
            if store.chunk_status.get((block_root, chunk_index + 1)) == CHUNK_STATUS_WAITING:
                try_execute_chunk(store, block_root, chunk_index + 1)
        
        # Check if all chunks executed
        check_block_finalization(store, block_root)
    else:
        store.chunk_status[(block_root, chunk_index)] = CHUNK_STATUS_INVALID
        store.block_finalized[block_root] = False
```

### `check_block_finalization`

```python
def check_block_finalization(store: Store, block_root: Root) -> None:
    """
    Finalize block after all chunks executed, validating hash chain.
    """
    block = store.blocks[block_root]
    bid = block.body.signed_execution_payload_bid.message
    
    # Check all chunks are executed
    for i in range(len(bid.chunk_roots)):
        if store.chunk_status.get((block_root, i)) != CHUNK_STATUS_VALID:
            return  # Not all chunks executed yet
    
    # Validate hash chain continuity
    parent_state = store.block_states[block_root]
    expected_parent_hash = parent_state.latest_chunk_hash
    
    chunk_hashes = []
    for i in range(len(bid.chunk_roots)):
        chunk = store.chunks[(block_root, i)]
        chunk_hash = store.chunk_hashes[(block_root, i)]
        chunk_hashes.append(chunk_hash)
        
        # Validate parent chunk hash
        if i == 0:
            # First chunk points to previous slot's last chunk
            if chunk.chunk_header.parent_chunk_hash != expected_parent_hash:
                store.block_finalized[block_root] = False
                return
        else:
            # Subsequent chunks point to previous chunk
            if chunk.chunk_header.parent_chunk_hash != chunk_hashes[i-1]:
                store.block_finalized[block_root] = False
                return
    
    # Finalize block with validated chunk chain
    result = engine_finalize_block(
        beacon_block_root=block_root,
        expected_state_root=block.state_root,
        chunk_hashes=chunk_hashes
    )
    
    if result.status == "VALID":
        store.block_finalized[block_root] = True
        store.block_states[block_root].latest_chunk_hash = chunk_hashes[-1]
    else:
        store.block_finalized[block_root] = False
```

### Modified `get_head`

```python
def get_head(store: Store) -> Root:
    """
    Only consider finalized blocks for head selection.
    """
    blocks = get_filtered_block_tree(store)
    
    # Filter to finalized blocks [Modified in EIP9999]
    valid_blocks = {
        root: block for root, block in blocks.items()
        if not has_chunks(store.blocks[root]) or 
           store.block_finalized.get(root, False)
    }
    
    # Apply existing fork choice rules
    return compute_head(store, valid_blocks)
```

### Helper functions for orphan chunks

#### `get_block_root_for_slot_proposer`

```python
def get_block_root_for_slot_proposer(
    store: Store,
    slot: Slot, 
    proposer: ValidatorIndex
) -> Optional[Root]:
    """
    Find block root for given slot and proposer.
    """
    for block_root, block in store.blocks.items():
        if block.slot == slot and block.proposer_index == proposer:
            return block_root
    return None
```

#### `try_execute_orphan_chunk`

```python
def try_execute_orphan_chunk(
    store: Store,
    slot: Slot,
    proposer: ValidatorIndex, 
    chunk_index: uint8
) -> None:
    """
    Try to execute orphan chunk if CALs available.
    """
    orphan_key = (slot, proposer, chunk_index)
    
    if orphan_key not in store.orphan_chunks:
        return
    
    # Gather required CALs
    required_cals = []
    for i in range(chunk_index):
        cal_key = (slot, proposer, i)
        if cal_key not in store.orphan_cals:
            return  # CAL not available yet
        required_cals.append(store.orphan_cals[cal_key])
    
    # Execute orphan chunk
    execute_orphan_chunk_with_cals(store, slot, proposer, chunk_index, required_cals)
```

#### `execute_orphan_chunk_with_cals`

```python
def execute_orphan_chunk_with_cals(
    store: Store,
    slot: Slot,
    proposer: ValidatorIndex,
    chunk_index: uint8,
    required_cals: List[ChunkAccessList]
) -> None:
    """
    Execute orphan chunk before block arrives.
    """
    orphan_key = (slot, proposer, chunk_index)
    chunk = store.orphan_chunks[orphan_key]
    
    # Mark as executing
    store.orphan_chunk_status[orphan_key] = CHUNK_STATUS_EXECUTING
    
    # Execute chunk (using parent state for slot)
    result = engine_execute_chunk_with_cals(
        beacon_block_root=Root(),  # Not yet known
        chunk=chunk,
        required_cals=required_cals
    )
    
    if result.status == "VALID":
        store.orphan_chunk_status[orphan_key] = CHUNK_STATUS_VALID
        
        # Store generated CAL
        store.orphan_cals[orphan_key] = result.chunk_access_list
        
        # Try to execute next orphan chunk
        if chunk_index + 1 < MAX_CHUNKS_PER_BLOCK:
            next_key = (slot, proposer, chunk_index + 1)
            if store.orphan_chunk_status.get(next_key) == CHUNK_STATUS_WAITING:
                try_execute_orphan_chunk(store, slot, proposer, chunk_index + 1)
    else:
        store.orphan_chunk_status[orphan_key] = CHUNK_STATUS_INVALID
```

## Engine API

### `engine_execute_chunk_with_cals`

```python
def engine_execute_chunk_with_cals(
    beacon_block_root: Root,
    chunk: ExecutionChunk,
    required_cals: List[ChunkAccessList]  # CALs 0..chunk.index-1
) -> ChunkExecutionResult:
    """
    Execute chunk by applying CALs to parent state, return generated CAL.
    """
```

### `engine_finalize_block`

```python
def engine_finalize_block(
    beacon_block_root: Root,
    expected_state_root: Root,
    chunk_hashes: List[Hash32]
) -> PayloadStatus:
    """
    Verify final state after all chunks executed.
    """
```

