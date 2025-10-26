# EIP-9999 -- The Beacon Chain

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This specification defines the changes made to the beacon chain to support payload chunking with Chunk Access Lists (CALs) as part of EIP-9999.

*Note*: This specification extends [Gloas](../../gloas/beacon-chain.md).

## Constants

### Chunking parameters

| Name | Value | Description |
| - | - | - |
| `CHUNK_GAS_LIMIT` | `uint64(2**24)` | Maximum gas per chunk (16,777,216) |
| `MAX_CHUNKS_PER_BLOCK` | `uint8(16)` | Maximum chunks in a block |
| `MIN_CHUNK_FILL_RATIO` | `0.5` | Non-terminal chunks must be ≥50% full |
| `CHUNK_INCLUSION_PROOF_DEPTH` | `uint64(5)` | Merkle proof depth for chunk inclusion |
| `MAX_CHUNK_ACCESS_LIST_SIZE` | `uint64(2**18)` | Maximum CAL size (256 KB) |

## Preset

### Max operations per block

| Name | Value |
| - | - |
| `MAX_TRANSACTIONS_PER_CHUNK` | `uint64(2**10)` | Maximum transactions per chunk (1024) |

## Containers

### New containers

#### `ExecutionChunkHeader`

```python
class ExecutionChunkHeader(Container):
    index: uint8                     # Position in block (0 to MAX_CHUNKS_PER_BLOCK-1)
    parent_chunk_hash: Hash32        # Hash of the parent chunk (previous chunk or last chunk of prev slot)
    timestamp: uint64                # Timestamp of chunk execution
    txs_root: Root                   # Merkle root of transactions
    receipts_root: Root             # Merkle root of receipts
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]  # Bloom filter for logs
    gas_used: uint64                # Gas consumed in chunk
    state_root: Root                # Post-execution state root
    withdrawals_root: Root          # Merkle root of withdrawals (only for last chunk)
```

#### `ExecutionChunk`

```python
class ExecutionChunk(Container):
    chunk_header: ExecutionChunkHeader
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_CHUNK]
    withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]  # Only in last chunk
```

#### `ChunkAccessList`

```python
class ChunkAccessList(ByteList[MAX_CHUNK_ACCESS_LIST_SIZE]):
    pass  # RLP-encoded state diffs from chunk execution
```

#### `ExecutionChunkSidecar`

```python
class ExecutionChunkSidecar(Container):
    block_root: Root
    chunk_index: uint8
    chunk: ExecutionChunk
    chunk_signature: BLSSignature
    chunk_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```

#### `ChunkAccessListSidecar`

```python
class ChunkAccessListSidecar(Container):
    block_root: Root
    chunk_index: uint8
    chunk_access_list: ChunkAccessList
    cal_signature: BLSSignature
    cal_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```

#### `ChunkExecutionResult`

```python
class ChunkExecutionResult(Container):
    status: uint8  # 0=VALID, 1=INVALID, 2=INSUFFICIENT_INFORMATION, 3=SYNCING
    chunk_index: uint8
    chunk_hash: Hash32  # Hash of the executed chunk
    validation_error: ByteList[MAX_ERROR_SIZE]  # Error details if INVALID
    missing_cal_indices: List[uint8, MAX_CHUNKS_PER_BLOCK]  # Missing CALs if INSUFFICIENT_INFORMATION
    post_state_root: Root  # State root after chunk execution if VALID
```

### Modified containers

#### Modified `ExecutionPayloadBid`

```python
class ExecutionPayloadBid(Container):
    # Existing fields from Gloas
    builder: ValidatorIndex
    value: Gwei
    kzg_commitments_root: Root
    state_root: Root
    parent_hash: Hash32
    builder_hash: Hash32
    withdrawals_root: Root
    
    # New fields for chunking [New in EIP9999]
    chunk_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Commitments to chunks
    chunk_access_list_roots: List[Root, MAX_CHUNKS_PER_BLOCK]  # Commitments to CALs
```

#### Modified `SignedExecutionPayloadEnvelope`

```python
class SignedExecutionPayloadEnvelope(Container):
    message: ExecutionPayloadEnvelope
    signature: BLSSignature
    # New fields [New in EIP9999]
    chunks: List[ExecutionChunk, MAX_CHUNKS_PER_BLOCK]
    chunk_access_lists: List[ChunkAccessList, MAX_CHUNKS_PER_BLOCK]
```

#### Modified `BeaconBlockBody`

```python
class BeaconBlockBody(Container):
    randao_reveal: BLSSignature
    eth1_data: Eth1Data
    graffiti: Bytes32
    proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
    attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS]
    attestations: List[Attestation, MAX_ATTESTATIONS]
    deposits: List[Deposit, MAX_DEPOSITS]
    voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
    sync_aggregate: SyncAggregate
    bls_to_execution_changes: List[SignedBLSToExecutionChange, MAX_BLS_TO_EXECUTION_CHANGES]
    blob_kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    consolidations: List[SignedConsolidation, MAX_CONSOLIDATIONS]
    # Gloas fields
    signed_execution_payload_bid: SignedExecutionPayloadBid  # [Modified in EIP9999]
    payload_attestations: List[PayloadAttestation, MAX_PAYLOAD_ATTESTATIONS]
```

#### Modified `BeaconState`

```python
class BeaconState(Container):
    # Versioning
    genesis_time: uint64
    genesis_validators_root: Root
    slot: Slot
    fork: Fork
    # History
    latest_block_header: BeaconBlockHeader
    block_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    state_roots: Vector[Root, SLOTS_PER_HISTORICAL_ROOT]
    historical_roots: List[Root, HISTORICAL_ROOTS_LIMIT]
    # Eth1
    eth1_data: Eth1Data
    eth1_data_votes: List[Eth1Data, EPOCHS_PER_ETH1_VOTING_PERIOD * SLOTS_PER_EPOCH]
    eth1_deposit_index: uint64
    # Registry
    validators: List[Validator, VALIDATOR_REGISTRY_LIMIT]
    balances: List[Gwei, VALIDATOR_REGISTRY_LIMIT]
    # Randomness
    randao_mixes: Vector[Bytes32, EPOCHS_PER_HISTORICAL_VECTOR]
    # Slashings
    slashings: Vector[Gwei, EPOCHS_PER_SLASHINGS_VECTOR]
    # Participation
    previous_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    current_epoch_participation: List[ParticipationFlags, VALIDATOR_REGISTRY_LIMIT]
    # Finality
    justification_bits: Bitvector[JUSTIFICATION_BITS_LENGTH]
    previous_justified_checkpoint: Checkpoint
    current_justified_checkpoint: Checkpoint
    finalized_checkpoint: Checkpoint
    # Inactivity
    inactivity_scores: List[uint64, VALIDATOR_REGISTRY_LIMIT]
    # Sync
    current_sync_committee: SyncCommittee
    next_sync_committee: SyncCommittee
    # Gloas
    latest_execution_payload_bid: ExecutionPayloadBid  # [Modified in EIP9999]
    next_withdrawal_index: WithdrawalIndex
    next_withdrawal_validator_index: ValidatorIndex
    historical_summaries: List[HistoricalSummary, HISTORICAL_ROOTS_LIMIT]
    deposit_requests_start_index: uint64
    deposit_balance_to_consume: Gwei
    exit_balance_to_consume: Gwei
    earliest_exit_epoch: Epoch
    consolidation_balance_to_consume: Gwei
    earliest_consolidation_epoch: Epoch
    pending_deposits: List[PendingDeposit, PENDING_DEPOSITS_LIMIT]
    pending_partial_withdrawals: List[PendingPartialWithdrawal, PENDING_PARTIAL_WITHDRAWALS_LIMIT]
    pending_consolidations: List[PendingConsolidation, PENDING_CONSOLIDATIONS_LIMIT]
    proposer_lookahead: ProposerLookahead
    execution_payload_availability: Bitvector[SLOTS_PER_HISTORICAL_ROOT]
    builder_pending_payments: List[BuilderPendingPayment, MAX_BUILDER_PENDING_PAYMENTS]
    builder_pending_withdrawals: List[BuilderPendingWithdrawal, MAX_BUILDER_PENDING_WITHDRAWALS]
    latest_withdrawals_root: Root
    
    # New fields for chunking [New in EIP9999]
    latest_chunk_hash: Hash32  # Hash of the last executed chunk (forms the chain)
    chunk_execution_status: List[ChunkExecutionResult, MAX_CHUNKS_PER_BLOCK]
    received_chunk_indices: Bitvector[MAX_CHUNKS_PER_BLOCK]
    received_cal_indices: Bitvector[MAX_CHUNKS_PER_BLOCK]
```

## Helper functions

### Chunk validation

#### `compute_chunk_hash`

```python
def compute_chunk_hash(chunk: ExecutionChunk) -> Hash32:
    """
    Compute chunk hash for chain continuity.
    """
    return hash(
        chunk.chunk_header.ssz_serialize() + 
        hash_tree_root(chunk.transactions) +
        hash_tree_root(chunk.withdrawals)
    )
```

#### `validate_chunk_structure`

```python
def validate_chunk_structure(chunk: ExecutionChunk, chunk_index: uint8) -> bool:
    """
    Validate chunk gas limits and structure.
    """
    if chunk.chunk_header.gas_used > CHUNK_GAS_LIMIT:
        return False
    if chunk.chunk_header.index != chunk_index:
        return False
    if len(chunk.withdrawals) > 0 and chunk_index != MAX_CHUNKS_PER_BLOCK - 1:
        return False
    return True
```

#### `validate_chunk_fill_ratio`

```python
def validate_chunk_fill_ratio(chunks: List[ExecutionChunk, MAX_CHUNKS_PER_BLOCK]) -> bool:
    """
    Non-terminal chunks must be ≥50% full or combined with next ≥ CHUNK_GAS_LIMIT.
    """
    for i in range(len(chunks) - 1):
        chunk = chunks[i]
        next_chunk = chunks[i + 1]
        if chunk.chunk_header.gas_used < MIN_CHUNK_FILL_RATIO * CHUNK_GAS_LIMIT:
            if chunk.chunk_header.gas_used + next_chunk.chunk_header.gas_used < CHUNK_GAS_LIMIT:
                return False
    return True
```

#### `validate_chunk_hash_chain`

```python
def validate_chunk_hash_chain(
    chunk: ExecutionChunk, 
    parent_chunk_hash: Hash32,
    chunk_index: uint8
) -> bool:
    """
    Validate parent hash and index match.
    """
    return (chunk.chunk_header.parent_chunk_hash == parent_chunk_hash and 
            chunk.chunk_header.index == chunk_index)
```

#### `compute_cal_root`

```python
def compute_cal_root(cal: ChunkAccessList) -> Root:
    return hash_tree_root(cal)
```

### Chunk execution

#### `mark_chunk_received`

```python
def mark_chunk_received(state: BeaconState, chunk_index: uint8) -> None:
    """
    Mark a chunk as received in the state
    """
    state.received_chunk_indices[chunk_index] = True
```

#### `mark_cal_received`

```python
def mark_cal_received(state: BeaconState, cal_index: uint8) -> None:
    """
    Mark a CAL as received in the state
    """
    state.received_cal_indices[cal_index] = True
```

#### `are_prerequisites_met`

```python
def are_prerequisites_met(state: BeaconState, chunk_index: uint8) -> bool:
    """
    Check if all prerequisites (prior CALs) are available for chunk execution
    """
    if chunk_index == 0:
        return True
    
    # Check all prior CALs are available
    for i in range(chunk_index):
        if not state.received_cal_indices[i]:
            return False
    
    return True
```

## Beacon chain state transition function

### Block processing

#### Modified `process_operations`

```python
def process_operations(state: BeaconState, body: BeaconBlockBody) -> None:
    # Existing Gloas operations
    # ...
    
    # Validate chunking commitments [New in EIP9999]
    if body.signed_execution_payload_bid is not None:
        bid = body.signed_execution_payload_bid.message
        assert len(bid.chunk_roots) > 0
        assert len(bid.chunk_roots) == len(bid.chunk_access_list_roots)
        assert len(bid.chunk_roots) <= MAX_CHUNKS_PER_BLOCK
```

### Chunk processing

#### `process_chunk_sidecar`

```python
def process_chunk_sidecar(state: BeaconState, sidecar: ExecutionChunkSidecar) -> None:
    """
    Process a received chunk sidecar
    """
    # Verify inclusion proof
    assert verify_merkle_proof(
        leaf=compute_chunk_root(sidecar.chunk),
        proof=sidecar.chunk_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=sidecar.chunk_index,
        root=state.latest_execution_payload_bid.chunk_roots[sidecar.chunk_index]
    )
    
    # Validate chunk structure
    assert validate_chunk_structure(sidecar.chunk, sidecar.chunk_index)
    
    # Mark chunk as received
    mark_chunk_received(state, sidecar.chunk_index)
    
    # Store execution result as pending
    state.chunk_execution_status[sidecar.chunk_index] = ChunkExecutionResult(
        status=2,  # INSUFFICIENT_INFORMATION
        chunk_index=sidecar.chunk_index,
        validation_error=ByteList[MAX_ERROR_SIZE](),
        missing_cal_indices=List[uint8, MAX_CHUNKS_PER_BLOCK](),
        post_state_root=Root()
    )
```

#### `process_cal_sidecar`

```python
def process_cal_sidecar(state: BeaconState, sidecar: ChunkAccessListSidecar) -> None:
    """
    Process a received CAL sidecar
    """
    # Verify inclusion proof
    assert verify_merkle_proof(
        leaf=compute_cal_root(sidecar.chunk_access_list),
        proof=sidecar.cal_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=sidecar.chunk_index,
        root=state.latest_execution_payload_bid.chunk_access_list_roots[sidecar.chunk_index]
    )
    
    # Mark CAL as received
    mark_cal_received(state, sidecar.chunk_index)
```

#### `can_execute_chunk`

```python
def can_execute_chunk(state: BeaconState, chunk_index: uint8) -> bool:
    """
    Check if a chunk can be executed based on available prerequisites
    """
    # Chunk must be received
    if not state.received_chunk_indices[chunk_index]:
        return False
    
    # Prerequisites must be met
    if not are_prerequisites_met(state, chunk_index):
        return False
    
    # Chunk must not already be executed
    if state.chunk_execution_status[chunk_index].status == 0:  # VALID
        return False
    
    return True
```