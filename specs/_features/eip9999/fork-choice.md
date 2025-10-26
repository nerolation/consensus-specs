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
    Initialize chunk tracking for streaming validation.
    """
    block = signed_block.message
    block_root = hash_tree_root(block)
    
    # Existing Gloas validation
    # ...
    
    # Initialize chunk tracking [New in EIP9999]
    if has_chunks(block):
        bid = block.body.signed_execution_payload_bid.message
        for i in range(len(bid.chunk_roots)):
            store.chunk_status[(block_root, i)] = CHUNK_STATUS_PENDING
        store.block_finalized[block_root] = False
```

### `on_execution_chunk_sidecar`

```python
def on_execution_chunk_sidecar(store: Store, sidecar: ExecutionChunkSidecar) -> None:
    """
    Handle chunk arrival - execute if CAL prerequisites are available.
    """
    block_root = sidecar.block_root
    chunk_index = sidecar.chunk_index
    
    # Validate sidecar structure and proof
    assert block_root in store.blocks
    block = store.blocks[block_root]
    assert validate_chunk_sidecar(store, sidecar)
    
    # Store chunk and hash
    chunk = sidecar.chunk
    store.chunks[(block_root, chunk_index)] = chunk
    store.chunk_hashes[(block_root, chunk_index)] = compute_chunk_hash(chunk)
    
    # Try to execute if prerequisites met
    if chunk_index == 0:
        # First chunk can execute immediately on parent state
        execute_chunk_with_cals(store, block_root, 0, [])
    else:
        # Check if required CALs are available
        store.chunk_status[(block_root, chunk_index)] = CHUNK_STATUS_WAITING
        try_execute_chunk(store, block_root, chunk_index)
```

### `on_chunk_access_list_sidecar`

```python
def on_chunk_access_list_sidecar(store: Store, sidecar: ChunkAccessListSidecar) -> None:
    """
    Handle CAL arrival - enables execution of dependent chunks.
    """
    block_root = sidecar.block_root
    cal_index = sidecar.chunk_index
    
    # Validate and store CAL
    assert validate_cal_sidecar(store, sidecar)
    store.chunk_access_lists[(block_root, cal_index)] = sidecar.chunk_access_list
    
    # Try to execute chunks waiting for this CAL
    # This creates the streaming cascade effect
    for i in range(cal_index + 1, MAX_CHUNKS_PER_BLOCK):
        if store.chunk_status.get((block_root, i)) == CHUNK_STATUS_WAITING:
            try_execute_chunk(store, block_root, i)
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

