# Payload Chunking -- Honest Validator

*Note*: This document is a work-in-progress for researchers and implementers.

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Prerequisites](#prerequisites)
- [Helpers](#helpers)
  - [`compute_subnet_for_chunk_sidecar`](#compute_subnet_for_chunk_sidecar)
  - [`compute_subnet_for_chunk_access_list_sidecar`](#compute_subnet_for_chunk_access_list_sidecar)
- [Beacon chain responsibilities](#beacon-chain-responsibilities)
  - [Block and sidecar proposal](#block-and-sidecar-proposal)
    - [Constructing the `BeaconBlockBody`](#constructing-the-beaconblockbody)
      - [Execution chunks](#execution-chunks)
      - [Chunk access lists](#chunk-access-lists)
    - [Chunk sidecars](#chunk-sidecars)
      - [`construct_chunk_sidecars`](#construct_chunk_sidecars)
    - [Chunk access list sidecars](#chunk-access-list-sidecars)
      - [`construct_chunk_access_list_sidecars`](#construct_chunk_access_list_sidecars)
  - [Block and sidecar publishing](#block-and-sidecar-publishing)
- [Attesting](#attesting)
  - [Attestation data](#attestation-data)
- [Chunk and chunk access list gossip](#chunk-and-chunk-access-list-gossip)

<!-- mdformat-toc end -->

## Introduction

This document specifies the validator duties for payload chunking, building upon [Gloas validator duties](../../gloas/validator.md).

Validators must handle two-phase validation:
- **Phase 1**: Validate individual chunks as they arrive (streaming)
- **Phase 2**: Verify complete state transition after all chunks received

Validators MUST NOT attest until both phases complete successfully.

## Prerequisites

This document assumes validators have access to an execution engine that supports payload chunking.

## Helpers

### `get_chunk_roots_from_payload_bid`

```python
def compute_subnet_for_chunk_sidecar(chunk_index: uint8) -> uint64:
    return chunk_index % EXECUTION_CHUNK_SUBNET_COUNT  # chunk_index % 16

def compute_subnet_for_chunk_access_list_sidecar(cal_index: uint8) -> uint64:
    return cal_index % CHUNK_ACCESS_LIST_SUBNET_COUNT  # cal_index % 16
```


## Beacon chain responsibilities

### Block and sidecar proposal

#### Constructing the `BeaconBlockBody`

##### Execution chunks

In the Gloas + payload chunking flow:

**For builder blocks:**
1. Proposer receives a `SignedExecutionPayloadBid` from the builder
2. The bid includes `chunk_roots` and `chunk_access_list_roots`
3. Proposer includes these roots in the beacon block body
4. Builder publishes the actual chunks and CALs as sidecars

**For local blocks:**
1. Proposer requests chunked payload from local execution engine
2. EL returns chunks and chunk access lists
3. Proposer computes roots and includes them in beacon block body
4. Proposer publishes chunks and CALs as sidecars

```python
def prepare_beacon_block_body_with_builder(
    state: BeaconState, 
    signed_bid: SignedExecutionPayloadBid
) -> BeaconBlockBody:
    bid = signed_bid.message
    
    chunk_roots = bid.chunk_roots
    chunk_access_list_roots = bid.chunk_access_list_roots
    
    body = BeaconBlockBody(
        ...  # Other fields as per Gloas
        signed_execution_payload_bid=signed_bid,
        chunk_roots=chunk_roots,
        chunk_access_list_roots=chunk_access_list_roots,
    )
    
    return body

def prepare_beacon_block_body_local(
    state: BeaconState,
    execution_engine: ExecutionEngine
) -> Tuple[BeaconBlockBody, List[ExecutionChunk], List[ChunkAccessList]]:
    chunked_payload = execution_engine.get_chunked_payload(
        state.latest_block_hash,
        state.slot
    )
    
    chunks = chunked_payload.chunks
    chunk_access_lists = chunked_payload.chunk_access_lists
    
    chunk_roots = [hash_tree_root(chunk) for chunk in chunks]
    chunk_access_list_roots = [hash_tree_root(cal) for cal in chunk_access_lists]
    
    local_bid = ExecutionPayloadBid(
        parent_block_hash=state.latest_block_hash,
        parent_block_root=state.latest_block_root,
        block_hash=compute_block_hash(chunks),  # Computed by EL
        fee_recipient=get_fee_recipient(state),
        gas_limit=sum(chunk.gas_used for chunk in chunks),
        builder_index=get_validator_index(state),  # Local validator index
        slot=state.slot,
        value=0,  # No payment for local block
        blob_kzg_commitments_root=compute_blob_kzg_commitments_root(chunks),
        chunk_roots=chunk_roots,
        chunk_access_list_roots=chunk_access_list_roots,
    )
    
    signed_bid = SignedExecutionPayloadBid(
        message=local_bid,
        signature=sign_bid(local_bid, get_domain(state, DOMAIN_BEACON_BUILDER))
    )
    
    body = BeaconBlockBody(
        ...  # Other fields
        signed_execution_payload_bid=signed_bid,
        chunk_roots=chunk_roots,
        chunk_access_list_roots=chunk_access_list_roots,
    )
    
    return body, chunks, chunk_access_lists
```

##### Chunk access lists

Chunk Access Lists (CALs) are required for chunk execution and propagate separately from chunks on dedicated gossip subnets. Validators must ensure all CALs are available before attestation.

#### Chunk sidecars


##### `construct_chunk_sidecars`

```python
def construct_chunk_sidecars(
    signed_block: SignedBeaconBlock,
    chunks: List[ExecutionChunk]
) -> List[ExecutionChunkSidecar]:
    block = signed_block.message
    signed_block_header = SignedBeaconBlockHeader(
        message=BeaconBlockHeader(
            slot=block.slot,
            proposer_index=block.proposer_index,
            parent_root=block.parent_root,
            state_root=block.state_root,
            body_root=hash_tree_root(block.body),
        ),
        signature=signed_block.signature,
    )
    
    sidecars = []
    for i, chunk in enumerate(chunks):
        inclusion_proof = compute_merkle_proof(
            block.body,
            get_generalized_index(BeaconBlockBody, "chunk_roots", i)
        )
        
        sidecar = ExecutionChunkSidecar(
            chunk=chunk,
            chunk_signature=signed_block_header,
            chunk_root_inclusion_proof=inclusion_proof,
        )
        sidecars.append(sidecar)
    
    return sidecars
```

#### Chunk access list sidecars


##### `construct_chunk_access_list_sidecars`

```python
def construct_chunk_access_list_sidecars(
    signed_block: SignedBeaconBlock,
    chunk_access_lists: List[ChunkAccessList]
) -> List[ChunkAccessListSidecar]:
    block = signed_block.message
    signed_block_header = SignedBeaconBlockHeader(
        message=BeaconBlockHeader(
            slot=block.slot,
            proposer_index=block.proposer_index,
            parent_root=block.parent_root,
            state_root=block.state_root,
            body_root=hash_tree_root(block.body),
        ),
        signature=signed_block.signature,
    )
    
    sidecars = []
    for i, cal in enumerate(chunk_access_lists):
        inclusion_proof = compute_merkle_proof(
            block.body,
            get_generalized_index(BeaconBlockBody, "chunk_access_list_roots", i)
        )
        
        sidecar = ChunkAccessListSidecar(
            chunk_access_list=cal,
            cal_signature=signed_block_header,
            cal_root_inclusion_proof=inclusion_proof,
        )
        sidecars.append(sidecar)
    
    return sidecars
```

### Block and sidecar publishing

Publishing depends on whether using a builder or local block:

**For builder blocks:**
1. Proposer publishes the beacon block (containing chunk roots from bid)
2. Builder is responsible for publishing chunk and CAL sidecars
3. If builder fails to publish, block becomes unavailable

**For local blocks:**
1. Proposer publishes the beacon block
2. Proposer publishes each chunk sidecar on `execution_chunk_sidecar_{subnet_id}`
3. Proposer publishes each CAL sidecar on `chunk_access_list_sidecar_{subnet_id}`

```python
def publish_block_builder_flow(signed_block: SignedBeaconBlock) -> None:
    gossip_publish("beacon_block", signed_block)

def publish_block_local_flow(
    signed_block: SignedBeaconBlock,
    chunk_sidecars: List[ExecutionChunkSidecar],
    cal_sidecars: List[ChunkAccessListSidecar]
) -> None:
    gossip_publish("beacon_block", signed_block)
    
    for sidecar in chunk_sidecars:
        chunk_index = sidecar.chunk.chunk_header.index
        subnet_id = compute_subnet_for_chunk_sidecar(chunk_index)
        gossip_publish(f"execution_chunk_sidecar_{subnet_id}", sidecar)
    
    for i, sidecar in enumerate(cal_sidecars):
        subnet_id = compute_subnet_for_chunk_access_list_sidecar(i)
        gossip_publish(f"chunk_access_list_sidecar_{subnet_id}", sidecar)
```


## Attesting

### Attestation data

Validators MUST NOT attest to a block until both validation phases complete:

```python
def is_block_available_for_attestation(
    store: Store,
    block_root: Root
) -> bool:
    """Check if block has passed two-phase validation
    
    Requirements:
    1. Phase 1: All chunks individually validated
    2. Phase 2: Complete state transition verified
    3. Final state root matches block header commitment
    """
    # Check Phase 1: All chunks validated
    if not all_chunks_validated(store, block_root):
        return False
    
    # Check Phase 2: State transition verified
    if not is_block_state_valid(store, block_root):
        return False
    
    # Verify all chunks and CALs are available
    if not is_payload_available(store, block_root):
        return False
    
    return True
```

## Chunk and chunk access list gossip

All validators must:

1. Subscribe to all chunk subnets (`execution_chunk_sidecar_{0..15}`)
2. Subscribe to all chunk access list subnets (`chunk_access_list_sidecar_{0..15}`)
3. Validate and forward valid sidecars according to the gossip rules
4. Pass chunks to the execution engine immediately for Phase 1 validation
5. Pass CALs to the execution engine for chunk processing

When receiving sidecars:
- Validate sidecars according to gossip rules
- Pass valid sidecars to fork choice handlers (`on_chunk`, `on_chunk_access_list`)

In future upgrades, validators may be assigned to custody only specific subnets, but initially all validators must maintain all chunks and chunk access lists for full availability.