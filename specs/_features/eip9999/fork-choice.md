# EIP-9999 -- Fork Choice

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document specifies the modifications to the fork choice for EIP-9999 Payload Chunking, introducing two-phase validation for chunked payloads.

## Custom types

| Name | SSZ equivalent | Description |
| - | - | - |
| `ChunkStatus` | `uint8` | Status of chunk execution |
| `BlockPhase` | `uint8` | Current phase of block validation |

## Constants

| Name | Value | Description |
| - | - | - |
| `CHUNK_STATUS_PENDING` | `ChunkStatus(0)` | Chunk not yet executed |
| `CHUNK_STATUS_VALID` | `ChunkStatus(1)` | Chunk successfully executed |
| `CHUNK_STATUS_INVALID` | `ChunkStatus(2)` | Chunk execution failed |
| `CHUNK_STATUS_SYNCING` | `ChunkStatus(3)` | Waiting for prerequisites |
| `BLOCK_PHASE_CHUNKING` | `BlockPhase(0)` | Phase 1: Executing chunks |
| `BLOCK_PHASE_FINALIZING` | `BlockPhase(1)` | Phase 2: Finalizing block |
| `BLOCK_PHASE_COMPLETE` | `BlockPhase(2)` | Both phases complete |

## Containers

### Modified `Store`

```python
@dataclass
class Store(object):
    # Existing Gloas fields
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
    checkpoint_states: Dict[Checkpoint, BeaconState] = field(default_factory=dict)
    latest_messages: Dict[ValidatorIndex, LatestMessage] = field(default_factory=dict)
    execution_payload_envelopes: Dict[Root, SignedExecutionPayloadEnvelope] = field(default_factory=dict)
    
    # New fields for chunking [New in EIP9999]
    chunks: Dict[Tuple[Root, uint8], ExecutionChunk] = field(default_factory=dict)
    chunk_access_lists: Dict[Tuple[Root, uint8], ChunkAccessList] = field(default_factory=dict)
    chunk_execution_status: Dict[Tuple[Root, uint8], ChunkStatus] = field(default_factory=dict)
    block_validation_phase: Dict[Root, BlockPhase] = field(default_factory=dict)
    block_final_state_valid: Dict[Root, bool] = field(default_factory=dict)
```

### New containers

#### `ChunkExecutionInfo`

```python
@dataclass
class ChunkExecutionInfo(object):
    chunk_index: uint8
    status: ChunkStatus
    post_state_root: Root
    error_message: Optional[str]
```

## Fork choice handlers

### Modified `on_block`

```python
def on_block(store: Store, signed_block: SignedBeaconBlock) -> None:
    """
    Modified to initiate two-phase validation for chunked blocks
    """
    block = signed_block.message
    
    # Existing Gloas validation
    # ...
    
    # Initialize block validation phase [New in EIP9999]
    if is_eip9999_block(block):
        store.block_validation_phase[hash_tree_root(block)] = BLOCK_PHASE_CHUNKING
        
        # Extract chunk commitments from bid
        bid = block.body.signed_execution_payload_bid.message
        for i, chunk_root in enumerate(bid.chunk_roots):
            store.chunk_execution_status[(hash_tree_root(block), i)] = CHUNK_STATUS_PENDING
    
    # Continue with existing validation
    # ...
```

### New `on_execution_chunk_sidecar`

```python
def on_execution_chunk_sidecar(store: Store, sidecar: ExecutionChunkSidecar) -> None:
    """
    Handle received chunk sidecar
    """
    block_root = sidecar.block_root
    chunk_index = sidecar.chunk_index
    
    # Verify block exists
    assert block_root in store.blocks
    block = store.blocks[block_root]
    
    # Verify chunk commitment
    bid = block.body.signed_execution_payload_bid.message
    assert chunk_index < len(bid.chunk_roots)
    
    # Verify inclusion proof
    assert verify_merkle_proof(
        leaf=compute_chunk_root(sidecar.chunk),
        proof=sidecar.chunk_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=chunk_index,
        root=bid.chunk_roots[chunk_index]
    )
    
    # Store chunk
    store.chunks[(block_root, chunk_index)] = sidecar.chunk
    
    # Try to execute chunk if prerequisites are met
    try_execute_chunk(store, block_root, chunk_index)
```

### New `on_chunk_access_list_sidecar`

```python
def on_chunk_access_list_sidecar(store: Store, sidecar: ChunkAccessListSidecar) -> None:
    """
    Handle received CAL sidecar
    """
    block_root = sidecar.block_root
    cal_index = sidecar.chunk_index
    
    # Verify block exists
    assert block_root in store.blocks
    block = store.blocks[block_root]
    
    # Verify CAL commitment
    bid = block.body.signed_execution_payload_bid.message
    assert cal_index < len(bid.chunk_access_list_roots)
    
    # Verify inclusion proof
    assert verify_merkle_proof(
        leaf=compute_cal_root(sidecar.chunk_access_list),
        proof=sidecar.cal_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=cal_index,
        root=bid.chunk_access_list_roots[cal_index]
    )
    
    # Store CAL
    store.chunk_access_lists[(block_root, cal_index)] = sidecar.chunk_access_list
    
    # Try to execute chunks that were waiting for this CAL
    for chunk_idx in range(cal_index + 1, MAX_CHUNKS_PER_BLOCK):
        if (block_root, chunk_idx) in store.chunks:
            try_execute_chunk(store, block_root, chunk_idx)
```

### New `try_execute_chunk`

```python
def try_execute_chunk(store: Store, block_root: Root, chunk_index: uint8) -> None:
    """
    Attempt to execute a chunk if all prerequisites are met
    """
    # Check if chunk is already executed
    if store.chunk_execution_status.get((block_root, chunk_index), CHUNK_STATUS_PENDING) != CHUNK_STATUS_PENDING:
        return
    
    # Check if chunk is available
    if (block_root, chunk_index) not in store.chunks:
        return
    
    # Check if all required CALs are available
    required_cals = []
    for i in range(chunk_index):
        if (block_root, i) not in store.chunk_access_lists:
            # Missing required CAL
            store.chunk_execution_status[(block_root, chunk_index)] = CHUNK_STATUS_SYNCING
            return
        required_cals.append(store.chunk_access_lists[(block_root, i)])
    
    # Execute chunk with CALs
    chunk = store.chunks[(block_root, chunk_index)]
    result = engine_execute_chunk_with_cals(
        block_root,
        chunk,
        required_cals
    )
    
    # Update status based on result
    if result.status == "VALID":
        store.chunk_execution_status[(block_root, chunk_index)] = CHUNK_STATUS_VALID
        # Check if all chunks are now executed
        check_block_finalization(store, block_root)
    elif result.status == "INVALID":
        store.chunk_execution_status[(block_root, chunk_index)] = CHUNK_STATUS_INVALID
        # Mark entire block as invalid
        mark_block_invalid(store, block_root)
    else:
        store.chunk_execution_status[(block_root, chunk_index)] = CHUNK_STATUS_SYNCING
```

### New `check_block_finalization`

```python
def check_block_finalization(store: Store, block_root: Root) -> None:
    """
    Check if all chunks are executed and finalize the block
    """
    block = store.blocks[block_root]
    bid = block.body.signed_execution_payload_bid.message
    num_chunks = len(bid.chunk_roots)
    
    # Check if all chunks are executed
    for i in range(num_chunks):
        status = store.chunk_execution_status.get((block_root, i), CHUNK_STATUS_PENDING)
        if status != CHUNK_STATUS_VALID:
            return  # Not all chunks executed yet
    
    # All chunks executed, move to finalization phase
    if store.block_validation_phase[block_root] == BLOCK_PHASE_CHUNKING:
        store.block_validation_phase[block_root] = BLOCK_PHASE_FINALIZING
        
        # Send finalization request to EL
        result = engine_finalize_block(
            block_root,
            block.state_root,
            num_chunks
        )
        
        if result.status == "VALID":
            store.block_validation_phase[block_root] = BLOCK_PHASE_COMPLETE
            store.block_final_state_valid[block_root] = True
        else:
            mark_block_invalid(store, block_root)
```

### Modified `get_head`

```python
def get_head(store: Store) -> Root:
    """
    Modified to only consider blocks that have completed both validation phases
    """
    # Get all valid blocks
    blocks = get_filtered_block_tree(store)
    
    # Filter to only include blocks with complete validation [Modified in EIP9999]
    valid_blocks = {}
    for block_root, block in blocks.items():
        if is_eip9999_block(store.blocks[block_root]):
            # Check if block has completed both phases
            if store.block_validation_phase.get(block_root) == BLOCK_PHASE_COMPLETE:
                if store.block_final_state_valid.get(block_root, False):
                    valid_blocks[block_root] = block
        else:
            # Pre-EIP9999 blocks use existing validation
            valid_blocks[block_root] = block
    
    # Continue with existing head selection logic on valid_blocks
    # ...
```

### Modified `on_attestation`

```python
def on_attestation(store: Store, attestation: Attestation, is_from_block: bool = False) -> None:
    """
    Modified to consider chunk availability for payload attestations
    """
    # Existing validation
    # ...
    
    # Check chunk availability for payload present attestations [New in EIP9999]
    if attestation.data.index == 1:  # Payload present
        block_root = attestation.data.beacon_block_root
        
        if is_eip9999_block(store.blocks[block_root]):
            # Require at least Phase 1 started (some chunks received)
            has_chunks = False
            bid = store.blocks[block_root].body.signed_execution_payload_bid.message
            for i in range(len(bid.chunk_roots)):
                if (block_root, i) in store.chunks:
                    has_chunks = True
                    break
            
            if not has_chunks:
                # Cannot attest to payload present without any chunks
                return
    
    # Continue with existing logic
    # ...
```

## Helper functions

### New `is_eip9999_block`

```python
def is_eip9999_block(block: BeaconBlock) -> bool:
    """
    Check if a block uses EIP9999 chunking
    """
    if block.body.signed_execution_payload_bid is None:
        return False
    
    bid = block.body.signed_execution_payload_bid.message
    return len(bid.chunk_roots) > 0
```

### New `count_available_chunks`

```python
def count_available_chunks(store: Store, block_root: Root) -> uint64:
    """
    Count how many chunks are available for a block
    """
    block = store.blocks[block_root]
    bid = block.body.signed_execution_payload_bid.message
    count = 0
    
    for i in range(len(bid.chunk_roots)):
        if (block_root, i) in store.chunks:
            count += 1
    
    return count
```

### New `count_executed_chunks`

```python
def count_executed_chunks(store: Store, block_root: Root) -> uint64:
    """
    Count how many chunks have been successfully executed
    """
    block = store.blocks[block_root]
    bid = block.body.signed_execution_payload_bid.message
    count = 0
    
    for i in range(len(bid.chunk_roots)):
        if store.chunk_execution_status.get((block_root, i)) == CHUNK_STATUS_VALID:
            count += 1
    
    return count
```

### New `get_chunk_availability_percentage`

```python
def get_chunk_availability_percentage(store: Store, block_root: Root) -> uint64:
    """
    Return percentage of chunks available (0-100)
    """
    block = store.blocks[block_root]
    bid = block.body.signed_execution_payload_bid.message
    total_chunks = len(bid.chunk_roots)
    
    if total_chunks == 0:
        return 100  # No chunks means fully available
    
    available = count_available_chunks(store, block_root)
    return (available * 100) // total_chunks
```

## Engine API integration

### New `engine_execute_chunk_with_cals`

```python
def engine_execute_chunk_with_cals(
    block_hash: Hash32,
    chunk: ExecutionChunk,
    required_cals: List[ChunkAccessList]
) -> ChunkExecutionResult:
    """
    Send chunk with required CALs to execution layer for validation
    """
    # Implementation calls EL with chunk and CALs
    # Returns execution result
    pass
```

### New `engine_finalize_block`

```python
def engine_finalize_block(
    block_hash: Hash32,
    expected_state_root: Root,
    total_chunks: uint8
) -> PayloadStatus:
    """
    Request EL to finalize block after all chunks are executed
    """
    # Implementation calls EL to finalize block
    # Returns final validation status
    pass
```