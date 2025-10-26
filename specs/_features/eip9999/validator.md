# EIP-9999 -- Honest Validator

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document represents the changes to the honest validator guide for EIP-9999 Payload Chunking, extending the Gloas validator responsibilities.

## Prerequisites

This document extends the [Gloas Honest Validator](../../gloas/validator.md) guide. All existing Gloas responsibilities remain unless explicitly modified here.

## Beacon chain responsibilities

### Attestation

#### Modified attestation timing

Validators must wait for chunk availability before attesting:

```python
def should_attest_to_block(state: BeaconState, block_root: Root, current_slot: Slot) -> Tuple[bool, uint8]:
    """
    Determine if validator should attest and what payload status to use
    """
    block = get_block(block_root)
    
    # Check if this is an EIP9999 block with chunks
    if is_eip9999_block(block):
        bid = block.body.signed_execution_payload_bid.message
        num_chunks = len(bid.chunk_roots)
        
        # Count available chunks
        chunks_available = count_available_chunks_for_block(block_root)
        cals_available = count_available_cals_for_block(block_root)
        
        # Determine attestation index based on availability
        if chunks_available == 0:
            # No chunks available yet
            return (True, 0)  # Attest with payload absent
        elif chunks_available < num_chunks:
            # Partial chunks available
            # Wait for more chunks or attest cautiously
            if get_time_in_slot() > ATTESTATION_DEADLINE_PARTIAL_CHUNKS:
                return (True, 0)  # Timeout, attest payload absent
            else:
                return (False, 0)  # Keep waiting
        else:
            # All chunks available
            if cals_available == num_chunks:
                # Full validation possible
                return (True, 1)  # Attest payload present
            else:
                # Chunks available but missing CALs
                if get_time_in_slot() > ATTESTATION_DEADLINE_MISSING_CALS:
                    return (True, 0)  # Timeout, attest payload absent
                else:
                    return (False, 0)  # Keep waiting
    else:
        # Non-EIP9999 block, use Gloas rules
        return apply_gloas_attestation_rules(state, block_root)
```

#### Attestation deadlines

| Name | Value | Description |
| - | - | - |
| `ATTESTATION_DEADLINE_PARTIAL_CHUNKS` | `uint64(3000)` | 3 seconds - deadline when chunks partially available |
| `ATTESTATION_DEADLINE_MISSING_CALS` | `uint64(4000)` | 4 seconds - deadline when chunks available but CALs missing |

### Block proposal

#### Constructing execution payload with chunks

When proposing a block with EIP9999 active, the proposer must handle chunked payloads:

```python
def prepare_execution_payload_with_chunks(state: BeaconState) -> ExecutionPayloadBid:
    """
    Prepare execution payload bid with chunk commitments
    """
    # Get base payload from builder/EL
    base_payload = get_execution_payload()
    
    # Split payload into chunks
    chunks = split_payload_into_chunks(base_payload)
    
    # Generate CALs for each chunk
    cals = []
    for i, chunk in enumerate(chunks):
        cal = generate_chunk_access_list(chunk, i)
        cals.append(cal)
    
    # Create bid with chunk commitments
    bid = ExecutionPayloadBid(
        builder=get_validator_index(),
        value=calculate_bid_value(base_payload),
        kzg_commitments_root=compute_kzg_commitments_root(base_payload),
        state_root=base_payload.state_root,
        parent_hash=base_payload.parent_hash,
        builder_hash=compute_builder_hash(),
        withdrawals_root=compute_withdrawals_root(base_payload),
        # New chunking fields
        chunk_roots=[compute_chunk_root(chunk) for chunk in chunks],
        chunk_access_list_roots=[compute_cal_root(cal) for cal in cals]
    )
    
    return bid
```

#### Publishing chunks and CALs

After the beacon block is published, the proposer (or builder in PBS) must publish chunks and CALs:

```python
def publish_chunks_and_cals(
    block: BeaconBlock,
    chunks: List[ExecutionChunk],
    cals: List[ChunkAccessList]
) -> None:
    """
    Publish chunk and CAL sidecars to the network
    """
    block_root = compute_block_root(block)
    bid = block.body.signed_execution_payload_bid.message
    
    # Publish each chunk sidecar
    for i, chunk in enumerate(chunks):
        sidecar = ExecutionChunkSidecar(
            block_root=block_root,
            chunk_index=i,
            chunk=chunk,
            chunk_signature=sign_chunk(chunk),
            chunk_root_inclusion_proof=compute_inclusion_proof(
                bid.chunk_roots,
                i
            )
        )
        
        subnet_id = i % CHUNK_SUBNET_COUNT
        publish_to_subnet(f"execution_chunk_sidecar_{subnet_id}", sidecar)
    
    # Publish each CAL sidecar
    for i, cal in enumerate(cals):
        sidecar = ChunkAccessListSidecar(
            block_root=block_root,
            chunk_index=i,
            chunk_access_list=cal,
            cal_signature=sign_cal(cal),
            cal_root_inclusion_proof=compute_inclusion_proof(
                bid.chunk_access_list_roots,
                i
            )
        )
        
        subnet_id = i % CAL_SUBNET_COUNT
        publish_to_subnet(f"chunk_access_list_sidecar_{subnet_id}", sidecar)
```

### Chunk and CAL validation

#### Validating received chunks

```python
def validate_chunk_sidecar(sidecar: ExecutionChunkSidecar) -> bool:
    """
    Validate a received chunk sidecar
    """
    # Get the block
    block = get_block(sidecar.block_root)
    if block is None:
        return False
    
    bid = block.body.signed_execution_payload_bid.message
    
    # Verify chunk index
    if sidecar.chunk_index >= len(bid.chunk_roots):
        return False
    
    # Verify inclusion proof
    if not verify_merkle_proof(
        leaf=compute_chunk_root(sidecar.chunk),
        proof=sidecar.chunk_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=sidecar.chunk_index,
        root=bid.chunk_roots[sidecar.chunk_index]
    ):
        return False
    
    # Verify chunk structure
    if not validate_chunk_structure(sidecar.chunk, sidecar.chunk_index):
        return False
    
    # Verify signature
    if not verify_chunk_signature(sidecar.chunk_signature, sidecar.chunk, bid.builder):
        return False
    
    return True
```

#### Validating received CALs

```python
def validate_cal_sidecar(sidecar: ChunkAccessListSidecar) -> bool:
    """
    Validate a received CAL sidecar
    """
    # Get the block
    block = get_block(sidecar.block_root)
    if block is None:
        return False
    
    bid = block.body.signed_execution_payload_bid.message
    
    # Verify CAL index
    if sidecar.chunk_index >= len(bid.chunk_access_list_roots):
        return False
    
    # Verify inclusion proof
    if not verify_merkle_proof(
        leaf=compute_cal_root(sidecar.chunk_access_list),
        proof=sidecar.cal_root_inclusion_proof,
        depth=CHUNK_INCLUSION_PROOF_DEPTH,
        index=sidecar.chunk_index,
        root=bid.chunk_access_list_roots[sidecar.chunk_index]
    ):
        return False
    
    # Verify size limit
    if len(sidecar.chunk_access_list) > MAX_CHUNK_ACCESS_LIST_SIZE:
        return False
    
    # Verify signature
    if not verify_cal_signature(sidecar.cal_signature, sidecar.chunk_access_list, bid.builder):
        return False
    
    return True
```

### Sync committee participation

Sync committee messages must consider chunk availability:

```python
def get_sync_committee_message(state: BeaconState, block_root: Root) -> SyncCommitteeMessage:
    """
    Create sync committee message considering chunk availability
    """
    block = get_block(block_root)
    
    if is_eip9999_block(block):
        # For EIP9999 blocks, only sign if chunks are sufficiently available
        bid = block.body.signed_execution_payload_bid.message
        num_chunks = len(bid.chunk_roots)
        chunks_available = count_available_chunks_for_block(block_root)
        
        # Require at least 50% chunk availability for sync committee signature
        if chunks_available < num_chunks // 2:
            return None  # Don't sign
    
    # Create and sign sync committee message
    return create_sync_committee_message(block_root)
```

## Builder responsibilities

When EIP9999 is active, builders have additional responsibilities:

### Chunk construction

Builders must construct chunks according to the rules:

```python
def construct_chunks(transactions: List[Transaction], withdrawals: List[Withdrawal]) -> List[ExecutionChunk]:
    """
    Split transactions into chunks following EIP9999 rules
    """
    chunks = []
    current_chunk_txs = []
    current_chunk_gas = 0
    
    for tx in transactions:
        tx_gas = calculate_transaction_gas(tx)
        
        # Check if transaction fits in current chunk
        if current_chunk_gas + tx_gas > CHUNK_GAS_LIMIT:
            # Finalize current chunk
            if current_chunk_gas >= MIN_CHUNK_FILL_RATIO * CHUNK_GAS_LIMIT:
                # Chunk is sufficiently full
                chunks.append(create_chunk(current_chunk_txs, len(chunks)))
                current_chunk_txs = [tx]
                current_chunk_gas = tx_gas
            else:
                # Chunk is underfilled, check combined rule
                if current_chunk_gas + tx_gas >= CHUNK_GAS_LIMIT:
                    # Combined gas is sufficient
                    chunks.append(create_chunk(current_chunk_txs, len(chunks)))
                    current_chunk_txs = [tx]
                    current_chunk_gas = tx_gas
                else:
                    # Must include transaction in current chunk despite limit
                    # This should not happen with proper gas accounting
                    raise Exception("Invalid chunk construction")
        else:
            # Add transaction to current chunk
            current_chunk_txs.append(tx)
            current_chunk_gas += tx_gas
    
    # Add final chunk with withdrawals
    final_chunk = create_chunk(current_chunk_txs, len(chunks), withdrawals)
    chunks.append(final_chunk)
    
    return chunks
```

### CAL generation

Builders must generate CALs during chunk execution:

```python
def generate_chunk_access_list(chunk: ExecutionChunk, chunk_index: uint8) -> ChunkAccessList:
    """
    Generate CAL containing state diffs from chunk execution
    """
    # Execute chunk and track state changes
    pre_state = get_chunk_pre_state(chunk_index)
    post_state, state_changes = execute_chunk_with_tracking(chunk, pre_state)
    
    # Encode state changes as CAL
    cal = encode_state_changes_to_cal(state_changes)
    
    return cal
```

## Slashing conditions

### Invalid chunk construction

A builder can be slashed for:
- Publishing chunks that violate gas limits
- Publishing chunks that don't match committed roots
- Publishing invalid CALs that don't match chunk execution

### Withholding chunks or CALs

A builder can be penalized for:
- Failing to publish committed chunks within the deadline
- Failing to publish CALs after chunks are published

## Incentives

### Chunk availability rewards

Validators are incentivized to maintain chunk availability:
- Attestations with correct payload status receive full rewards
- Incorrect payload status attestations receive reduced rewards
- Validators hosting chunk/CAL subnets may receive priority fees

### Builder incentives

Builders are incentivized to:
- Construct efficient chunks that minimize state contention
- Publish chunks and CALs quickly to enable validation
- Maintain high availability for chunk distribution