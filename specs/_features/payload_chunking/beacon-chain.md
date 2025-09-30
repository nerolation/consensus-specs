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

Payload chunking splits execution layer blocks into multiple self-contained chunks with bounded gas limits that propagate independently as sidecars. Each chunk can be validated immediately upon arrival, enabling streaming validation that reduces block processing latency. 

Payload chunking splits execution layer blocks into multiple self-contained chunks with bounded gas limits. Chunks and their associated Chunk Access Lists (CALs) propagate independently as sidecars, enabling streaming validation.

- Chunks are self-contained execution units with their own headers and post-state roots
- Transactions cannot be split across chunks
- Each chunk respects a gas limit of `CHUNK_GAS_LIMIT` (2^24 gas)
- Non-terminal chunks must be at least half full (`MIN_CHUNK_FILL_RATIO = 0.5`)
- Withdrawals are included only in the final chunk
- The post-state of chunk *i* becomes the pre-state of chunk *i+1*
- CALs are opaque byte sequences from the CL perspective


## Custom types

| Name | SSZ equivalent | Description |
| ---- | -------------- | ----------- |
| `ChunkAccessList` | `ByteList[MAX_CHUNK_ACCESS_LIST_SIZE]` | Chunk access list for execution layer |
| `BlockAccessList` | `ByteList[MAX_BYTES_PER_TRANSACTION]` | RLP encoded block access list (from EIP-7928) |

## Constants

### Misc

| Name | Value | Description |
| ---- | ----- | ----------- |
| `CHUNK_GAS_LIMIT` | `uint64(2**24)` (= 16,777,216) | Maximum gas per chunk |
| `MIN_CHUNK_FILL_RATIO` | `0.5` | Non-terminal chunks must use at least 50% of gas limit |
| `CHUNK_INCLUSION_PROOF_DEPTH` | `uint64(5)` | Merkle proof depth for chunk_roots list item |
| `CHUNK_ACCESS_LIST_INCLUSION_PROOF_DEPTH` | `uint64(5)` | Merkle proof depth for chunk_access_list_roots list item |

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


#### `ExecutionChunkHeader`

```python
class ExecutionChunkHeader(Container):
    index: uint8                    # Position in block (0 to MAX_CHUNKS_PER_BLOCK-1)
    txs_root: Root                  # Merkle root of transactions
    post_state_root: Root           # State root after chunk execution
    receipts_root: Root             # Merkle root of receipts
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]  # Bloom filter for logs
    gas_used: uint64                # Gas consumed in chunk
    withdrawals_root: Root          # Merkle root of withdrawals (if present)
```

#### `ExecutionChunk`

```python
class ExecutionChunk(Container):
    chunk_header: ExecutionChunkHeader
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
    withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]  # Only in last chunk
```

#### `ExecutionChunkSidecar`

```python
class ExecutionChunkSidecar(Container):
    chunk: ExecutionChunk
    chunk_signature: SignedBeaconBlockHeader  # Proposer signature for authentication
    chunk_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```

#### `ChunkAccessListSidecar`

```python
class ChunkAccessListSidecar(Container):
    chunk_access_list: ChunkAccessList
    cal_signature: SignedBeaconBlockHeader
    cal_root_inclusion_proof: Vector[Bytes32, CHUNK_ACCESS_LIST_INCLUSION_PROOF_DEPTH]
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
    # Verify we have all chunks and CALs
    assert len(chunks) == len(body.chunk_roots)
    assert len(chunk_access_lists) == len(body.chunk_access_list_roots)
    
    # Verify chunk indices are sequential
    for i, chunk_sidecar in enumerate(chunks):
        assert chunk_sidecar.chunk.chunk_header.index == i
    
    # Verify chunks respect gas limit and minimum fill requirements
    for i, chunk_sidecar in enumerate(chunks):
        chunk = chunk_sidecar.chunk
        assert chunk.chunk_header.gas_used <= CHUNK_GAS_LIMIT
        
        # Non-terminal chunks must be at least MIN_CHUNK_FILL_RATIO full
        is_last_chunk = (i == len(chunks) - 1)
        if not is_last_chunk:
            assert chunk.chunk_header.gas_used >= CHUNK_GAS_LIMIT * MIN_CHUNK_FILL_RATIO
    
    # Verify state continuity between chunks
    for i in range(1, len(chunks)):
        prev_chunk = chunks[i-1].chunk
        curr_chunk = chunks[i].chunk
        # Note: State continuity is verified during execution
        # prev_chunk.chunk_header.post_state_root should equal curr_chunk's pre-state
    
    # Verify last chunk contains withdrawals if expected
    last_chunk = chunks[-1].chunk
    expected_withdrawals = get_expected_withdrawals(state)
    if len(expected_withdrawals) > 0:
        assert len(last_chunk.withdrawals) > 0
    
    # Verify non-last chunks don't contain withdrawals
    for chunk_sidecar in chunks[:-1]:
        assert len(chunk_sidecar.chunk.withdrawals) == 0
```

## Beacon chain state transition function

### Block processing

#### Execution payload processing

The execution payload processing follows a two-phase validation approach:

**Phase 1: Chunk Validation (Streaming)**
- Each chunk is validated independently as it arrives
- Chunks can be executed using previous chunk's post-state OR by applying prior CALs
- Validation includes transaction validity, gas limits, and internal consistency
- This phase enables early rejection of invalid blocks

**Phase 2: Block State Validation**
- After all chunks are received and validated
- Verifies state continuity between chunks
- Ensures final state root matches block header commitment
- Block is only valid if ALL chunks pass validation AND final state matches

```python
def process_execution_payload(state: BeaconState, 
                             body: BeaconBlockBody, 
                             execution_engine: ExecutionEngine) -> None:
    # Two-phase validation:
    # Phase 1: Individual chunk validation (handled by fork choice on_chunk)
    # Phase 2: Complete state transition verification
    block_root = hash_tree_root(body)
    
    # Verify all chunks have been validated (Phase 1 complete)
    for i in range(len(body.chunk_roots)):
        assert execution_engine.is_chunk_validated(block_root, i)
    
    # Verify final state transition (Phase 2)
    assert execution_engine.is_payload_finalized(block_root)
    
    # Verify final state matches header commitment
    final_chunk_index = len(body.chunk_roots) - 1
    final_state_root = execution_engine.get_chunk_post_state_root(block_root, final_chunk_index)
    assert final_state_root == body.state_root
```