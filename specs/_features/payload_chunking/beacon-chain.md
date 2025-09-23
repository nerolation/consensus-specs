# Payload Chunking -- The Beacon Chain

*Note*: This document is a work-in-progress for researchers and implementers.

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Constants](#constants)
  - [Misc](#misc)
- [Preset](#preset)
  - [Misc](#misc-1)
  - [Max operations per block](#max-operations-per-block)
- [Containers](#containers)
  - [New containers](#new-containers)
    - [`ExecutionChunk`](#executionchunk)
    - [`ExecutionChunkSidecar`](#executionchunksidecar)
    - [`ChunkAccessListSidecar`](#chunkaccesslistsidecar)
  - [Modified containers](#modified-containers)
    - [`ExecutionPayloadBid`](#executionpayloadbid)
    - [`ExecutionPayloadHeader`](#executionpayloadheader)
    - [`ExecutionPayloadEnvelope`](#executionpayloadenvelope)
    - [`BeaconBlockBody`](#beaconblockbody)
- [Helper functions](#helper-functions)
  - [Misc](#misc-2)
    - [`verify_chunk_inclusion_proof`](#verify_chunk_inclusion_proof)
    - [`verify_chunk_access_list_inclusion_proof`](#verify_chunk_access_list_inclusion_proof)
    - [`process_execution_chunks`](#process_execution_chunks)
- [Beacon chain state transition function](#beacon-chain-state-transition-function)
  - [Block processing](#block-processing)
    - [Execution payload processing](#execution-payload-processing)

<!-- mdformat-toc end -->

## Introduction

This feature implements payload chunking for the Ethereum consensus layer, building upon [Gloas](../../gloas/beacon-chain.md).

Payload chunking splits execution layer blocks into multiple chunks with bounded gas limits that propagate independently as sidecars. Chunks are passed to the execution layer immediately upon arrival for streaming validation. Chunk access lists propagate as separate sidecars to enable independent execution, where chunk N requires access lists from chunks 0 to N-1.

- Transactions cannot be split across chunks
- Each chunk respects a gas limit of `CHUNK_GAS_LIMIT` (2^24 gas)
- Chunks must be at least half full (except the last chunk)
- Withdrawals are included only in the last chunk
- The post-state of chunk *i* is the pre-state of chunk *i+1*


## Custom types

| Name | SSZ equivalent | Description |
| ---- | -------------- | ----------- |
| `ChunkAccessList` | `ByteList[MAX_CHUNK_ACCESS_LIST_SIZE]` | RLP encoded chunk access list |
| `BlockAccessList` | `ByteList[MAX_BYTES_PER_TRANSACTION]` | RLP encoded block access list (from EIP-7928) |

## Constants

### Misc

| Name | Value | Description |
| ---- | ----- | ----------- |
| `CHUNK_GAS_LIMIT` | `uint64(2**24)` (= 16,777,216) | Maximum gas per chunk |
| `CHUNK_INCLUSION_PROOF_DEPTH` | `uint64(floorlog2(get_generalized_index(BeaconBlockBody, 'chunk_roots')) + 1 + ceillog2(MAX_CHUNKS_PER_BLOCK))` | Merkle proof depth for chunk_roots list item |
| `CHUNK_ACCESS_LIST_INCLUSION_PROOF_DEPTH` | `uint64(floorlog2(get_generalized_index(BeaconBlockBody, 'chunk_access_list_roots')) + 1 + ceillog2(MAX_CHUNKS_PER_BLOCK))` | Merkle proof depth for chunk_access_list_roots list item |

## Preset

### Misc

| Name | Value | Description |
| ---- | ----- | ----------- |
| `MAX_CHUNKS_PER_BLOCK` | `uint64(16)` | Maximum number of chunks in a block |

### Max operations per block

| Name | Value | Description |
| ---- | ----- | ----------- |
| `MAX_CHUNK_ACCESS_LIST_SIZE` | `uint64(2**19)` (= 524,288) | Maximum size of a chunk access list in bytes |
| `MAX_BYTES_PER_TRANSACTION` | `uint64(2**30)` (= 1,073,741,824) | Maximum bytes per transaction (from Bellatrix) |

## Containers

### New containers


#### `ExecutionChunk`

```python
class ExecutionChunk(Container):
    index: uint64  # Chunk index within the block
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]  # Serialized transactions (complete, not split)
    withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]  # Only included in last chunk
    post_state_root: Root  # State root after executing this chunk
    gas_used: uint64  # Gas used by this chunk
    chunk_access_list: ChunkAccessList  # RLP encoded access list for this chunk
```

#### `ExecutionChunkSidecar`

```python
class ExecutionChunkSidecar(Container):
    index: uint64  # Chunk index
    chunk: ExecutionChunk
    signed_block_header: SignedBeaconBlockHeader
    chunk_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```


#### `ChunkAccessListSidecar`

```python
class ChunkAccessListSidecar(Container):
    index: uint64  # Chunk access list index
    chunk_access_list: ChunkAccessList  # RLP encoded chunk access list
    signed_block_header: SignedBeaconBlockHeader
    chunk_access_list_root_inclusion_proof: Vector[Bytes32, CHUNK_ACCESS_LIST_INCLUSION_PROOF_DEPTH]
```

### Modified containers

#### `ExecutionPayloadBid`

*Note*: Extends the Gloas `ExecutionPayloadBid`.

```python
class ExecutionPayloadBid(Container):
    # Existing fields from Gloas
    parent_block_hash: Hash32
    parent_block_root: Root
    block_hash: Hash32
    fee_recipient: ExecutionAddress
    gas_limit: uint64
    builder_index: ValidatorIndex
    slot: Slot
    value: Gwei
    blob_kzg_commitments_root: Root
    # New in Payload Chunking
    chunk_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Commitments to chunks
    chunk_access_list_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Commitments to chunk access lists
```

#### `ExecutionPayloadHeader`

*Note*: Extends the Gloas `ExecutionPayloadHeader`.

```python
class ExecutionPayloadHeader(Container):
    # Existing fields from Gloas
    parent_hash: Hash32
    fee_recipient: ExecutionAddress
    state_root: Bytes32
    receipts_root: Bytes32
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    prev_randao: Bytes32
    block_number: uint64
    gas_limit: uint64
    gas_used: uint64
    timestamp: uint64
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: uint256
    block_hash: Hash32
    transactions_root: Root
    withdrawals_root: Root
    blob_gas_used: uint64
    excess_blob_gas: uint64
    # New in Payload Chunking
    chunk_count: uint64  # Number of chunks in this payload
```

#### `ExecutionPayloadEnvelope`

*Note*: Extends the Gloas `ExecutionPayloadEnvelope`.

```python
class ExecutionPayloadEnvelope(Container):
    # Removed `payload` field - chunks carry the actual payload data
    execution_payload_header: ExecutionPayloadHeader  # New field replacing payload
    execution_requests: ExecutionRequests
    builder_index: ValidatorIndex
    beacon_block_root: Root
    slot: Slot
    blob_kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    state_root: Root
```

#### `BeaconBlockBody`

*Note*: Extends the Gloas `BeaconBlockBody`.

```python
class BeaconBlockBody(Container):
    randao_reveal: BLSSignature
    eth1_data: Eth1Data
    graffiti: Bytes32
    proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
    attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS_ELECTRA]
    attestations: List[Attestation, MAX_ATTESTATIONS_ELECTRA]
    deposits: List[Deposit, MAX_DEPOSITS]
    voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
    sync_aggregate: SyncAggregate
    bls_to_execution_changes: List[SignedBLSToExecutionChange, MAX_BLS_TO_EXECUTION_CHANGES]
    # Gloas fields
    signed_execution_payload_bid: SignedExecutionPayloadBid
    payload_attestations: List[PayloadAttestation, MAX_PAYLOAD_ATTESTATIONS]
    # New in Payload Chunking
    chunk_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Roots of execution chunks
    chunk_access_list_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Roots of chunk access lists
```

## Helper functions

### Misc

#### `verify_chunk_inclusion_proof`

```python
def verify_chunk_inclusion_proof(chunk_sidecar: ExecutionChunkSidecar) -> bool:
    gindex = get_subtree_index(
        get_generalized_index(BeaconBlockBody, "chunk_roots", chunk_sidecar.index)
    )
    return is_valid_merkle_branch(
        leaf=hash_tree_root(chunk_sidecar.chunk),
        branch=chunk_sidecar.chunk_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=gindex,
        root=chunk_sidecar.signed_block_header.message.body_root,
    )
```

#### `verify_chunk_access_list_inclusion_proof`

```python
def verify_chunk_access_list_inclusion_proof(cal_sidecar: ChunkAccessListSidecar) -> bool:
    gindex = get_subtree_index(
        get_generalized_index(BeaconBlockBody, "chunk_access_list_roots", cal_sidecar.index)
    )
    return is_valid_merkle_branch(
        leaf=hash_tree_root(cal_sidecar.chunk_access_list),
        branch=cal_sidecar.chunk_access_list_root_inclusion_proof,
        depth=CHUNK_ACCESS_LIST_INCLUSION_PROOF_DEPTH,
        index=gindex,
        root=cal_sidecar.signed_block_header.message.body_root,
    )
```

#### `process_execution_chunks`

```python
def process_execution_chunks(state: BeaconState, 
                            body: BeaconBlockBody,
                            chunks: List[ExecutionChunkSidecar],
                            chunk_access_lists: List[ChunkAccessListSidecar]) -> None:
    # Verify we have all chunks
    assert len(chunks) == len(body.chunk_roots)
    assert len(chunk_access_lists) == len(body.chunk_access_list_roots)
    
    # Verify chunk indices are sequential
    for i, chunk_sidecar in enumerate(chunks):
        assert chunk_sidecar.chunk.index == i
    
    # Verify chunk access list indices are sequential
    for i, cal_sidecar in enumerate(chunk_access_lists):
        assert cal_sidecar.index == i
    
    # Verify chunks respect gas limit and minimum fill requirements
    for i, chunk_sidecar in enumerate(chunks):
        chunk = chunk_sidecar.chunk
        assert chunk.gas_used <= CHUNK_GAS_LIMIT
        
        # Chunks must be at least half full, except for the last chunk
        is_last_chunk = (i == len(chunks) - 1)
        if not is_last_chunk:
            assert chunk.gas_used >= CHUNK_GAS_LIMIT // 2
    
    # Verify last chunk contains withdrawals
    last_chunk = chunks[-1].chunk
    assert len(last_chunk.withdrawals) > 0 or get_expected_withdrawals(state) == []
    
    # Verify non-last chunks don't contain withdrawals
    for chunk_sidecar in chunks[:-1]:
        assert len(chunk_sidecar.chunk.withdrawals) == 0
```

## Beacon chain state transition function

### Block processing

#### Execution payload processing

The execution payload processing is modified to handle chunks instead of a monolithic payload.

```python
def process_execution_payload(state: BeaconState, 
                             body: BeaconBlockBody, 
                             execution_engine: ExecutionEngine) -> None:
    # Chunks processed via fork choice handlers
    block_root = hash_tree_root(body)
    assert execution_engine.is_payload_finalized(block_root)
```