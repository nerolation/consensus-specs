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

## Custom types

| Name | SSZ equivalent | Description |
| ---- | -------------- | ----------- |
| `ChunkIndex` | `uint64` | Index of a chunk within a block |

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
    payload_chunk_availability: Dict[Root, bool] = field(default_factory=dict)
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
                     parent_root: Root) -> bool:
    return execution_engine.new_chunk(
        block_root=block_root,
        chunk=chunk,
        parent_root=parent_root
    )
```

### `notify_new_chunk_access_list`

```python
def notify_new_chunk_access_list(execution_engine: ExecutionEngine,
                                 block_root: Root,
                                 index: uint64,
                                 chunk_access_list: ChunkAccessList) -> None:
    # To execute chunk N, the EL requires CALs 0 through N-1
    execution_engine.new_chunk_access_list(
        block_root=block_root,
        index=index,
        chunk_access_list=chunk_access_list
    )
```

### `finalize_chunked_payload`

```python
def finalize_chunked_payload(execution_engine: ExecutionEngine,
                            block_root: Root,
                            expected_chunks: uint64) -> bool:
    return execution_engine.finalize_payload(
        block_root=block_root,
        expected_chunks=expected_chunks
    )
```

## Handlers

### `on_chunk`

```python
def on_chunk(store: Store, chunk_sidecar: ExecutionChunkSidecar) -> None:
    # Verify the chunk sidecar signature and inclusion proof
    assert verify_chunk_inclusion_proof(chunk_sidecar)
    
    # Verify chunk properties
    assert chunk_sidecar.chunk.index == chunk_sidecar.index
    assert chunk_sidecar.chunk.gas_used <= CHUNK_GAS_LIMIT
    
    block_root = chunk_sidecar.signed_block_header.message.body_root
    
    # Store the chunk
    store.chunks[(block_root, chunk_sidecar.index)] = chunk_sidecar.chunk
    
    execution_engine.notify_new_chunk(
        block_root,
        chunk_sidecar.chunk,
        chunk_sidecar.signed_block_header.message.parent_root
    )
    
    # Check if all chunks are now available for this block
    if block_root in store.blocks:
        block = store.blocks[block_root]
        all_chunks_available = all(
            is_chunk_available(store, block_root, i) 
            for i in range(len(block.body.chunk_roots))
        )
        
        if all_chunks_available:
            # Check if we also have all chunk access lists
            all_cals_available = all(
                is_chunk_access_list_available(store, block_root, i)
                for i in range(len(block.body.chunk_access_list_roots))
            )
            
            if all_cals_available:
                # Mark payload as available
                store.payload_chunk_availability[block_root] = True
                
                finalize_payload_validation(store, block_root)
```

### `on_chunk_access_list`

```python
def on_chunk_access_list(store: Store, cal_sidecar: ChunkAccessListSidecar) -> None:
    # Verify the CAL sidecar signature and inclusion proof
    assert verify_chunk_access_list_inclusion_proof(cal_sidecar)
    
    block_root = cal_sidecar.signed_block_header.message.body_root
    
    # Store the chunk access list
    store.chunk_access_lists[(block_root, cal_sidecar.index)] = cal_sidecar.chunk_access_list
    
    execution_engine.notify_new_chunk_access_list(
        block_root,
        cal_sidecar.index,
        cal_sidecar.chunk_access_list
    )
    
    # Check if all chunk access lists are now available for this block
    if block_root in store.blocks:
        block = store.blocks[block_root]
        all_cals_available = all(
            is_chunk_access_list_available(store, block_root, i)
            for i in range(len(block.body.chunk_access_list_roots))
        )
        
        if all_cals_available:
            # Check if we also have all chunks
            all_chunks_available = all(
                is_chunk_available(store, block_root, i)
                for i in range(len(block.body.chunk_roots))
            )
            
            if all_chunks_available:
                # Mark payload as available
                store.payload_chunk_availability[block_root] = True
                
                finalize_payload_validation(store, block_root)
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
def finalize_payload_validation(store: Store, block_root: Root) -> None:
    block = store.blocks[block_root]
    is_valid = execution_engine.finalize_chunked_payload(
        block_root,
        len(block.body.chunk_roots)
    )
    
    if is_valid:
        store.execution_payload_states[block_root] = True
        
        # Process block for fork choice if not already done
        if block_root not in store.block_states:
            process_block_for_fork_choice(store, block_root)
    else:
        del store.blocks[block_root]
        if block_root in store.payload_chunk_availability:
            del store.payload_chunk_availability[block_root]
```

```python
def process_block_for_fork_choice(store: Store, block_root: Root) -> None:
    block = store.blocks[block_root]
    
    state = store.block_states[block.parent_root].copy()
    state_transition(state, signed_block, validate_result=False)
    store.block_states[block_root] = state
```