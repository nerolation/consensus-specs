# EIP-9999 -- Builder Specification

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document specifies the builder behavior for EIP-9999 Payload Chunking in the context of enshrined Proposer-Builder Separation (ePBS) from Gloas.

## Builder responsibilities

### Payload construction

#### Chunked payload assembly

Builders must construct execution payloads that can be efficiently split into chunks:

```python
def build_chunked_payload(
    parent_hash: Hash32,
    timestamp: uint64,
    random: Bytes32,
    fee_recipient: ExecutionAddress,
    transactions: List[Transaction],
    withdrawals: List[Withdrawal]
) -> Tuple[List[ExecutionChunk], List[ChunkAccessList]]:
    """
    Build execution payload as chunks with CALs
    """
    # Sort and order transactions for optimal chunking
    ordered_txs = order_transactions_for_chunking(transactions)
    
    # Split into chunks following gas and fill rules
    chunks = []
    current_chunk_txs = []
    current_gas = 0
    
    for tx in ordered_txs:
        tx_gas = estimate_transaction_gas(tx)
        
        if current_gas + tx_gas > CHUNK_GAS_LIMIT:
            # Check fill ratio requirements
            if not validate_chunk_fill(current_gas, tx_gas):
                # Reorder or adjust to meet requirements
                current_chunk_txs = rebalance_chunk(current_chunk_txs, tx)
            
            # Create chunk
            chunk = create_execution_chunk(
                index=len(chunks),
                parent_hash=parent_hash if len(chunks) == 0 else Hash32(),
                transactions=current_chunk_txs,
                withdrawals=[] if len(chunks) < MAX_CHUNKS_PER_BLOCK - 1 else withdrawals
            )
            chunks.append(chunk)
            
            # Reset for next chunk
            current_chunk_txs = [tx] if current_gas + tx_gas > CHUNK_GAS_LIMIT else current_chunk_txs + [tx]
            current_gas = tx_gas if current_gas + tx_gas > CHUNK_GAS_LIMIT else current_gas + tx_gas
        else:
            current_chunk_txs.append(tx)
            current_gas += tx_gas
    
    # Add final chunk
    if current_chunk_txs or withdrawals:
        final_chunk = create_execution_chunk(
            index=len(chunks),
            parent_hash=parent_hash if len(chunks) == 0 else Hash32(),
            transactions=current_chunk_txs,
            withdrawals=withdrawals
        )
        chunks.append(final_chunk)
    
    # Generate CALs by executing chunks
    cals = generate_cals_for_chunks(chunks, parent_hash)
    
    return chunks, cals
```

### Bid construction

#### Creating execution payload bid with chunks

```python
def create_execution_payload_bid_with_chunks(
    validator_index: ValidatorIndex,
    chunks: List[ExecutionChunk],
    cals: List[ChunkAccessList],
    value: Gwei
) -> SignedExecutionPayloadBid:
    """
    Create bid committing to chunks and CALs
    """
    # Compute chunk and CAL commitments
    chunk_roots = [compute_chunk_root(chunk) for chunk in chunks]
    cal_roots = [compute_cal_root(cal) for cal in cals]
    
    # Extract necessary fields from chunks
    state_root = compute_final_state_root(chunks, cals)
    parent_hash = chunks[0].chunk_header.parent_hash
    withdrawals_root = compute_withdrawals_root(chunks[-1].withdrawals)
    
    # Create bid
    bid = ExecutionPayloadBid(
        builder=validator_index,
        value=value,
        kzg_commitments_root=Root(),  # No blobs in chunks
        state_root=state_root,
        parent_hash=parent_hash,
        builder_hash=compute_builder_hash(),
        withdrawals_root=withdrawals_root,
        chunk_roots=chunk_roots,
        chunk_access_list_roots=cal_roots
    )
    
    # Sign bid
    signature = sign_execution_payload_bid(bid)
    
    return SignedExecutionPayloadBid(
        message=bid,
        signature=signature
    )
```

### Chunk optimization

#### State access optimization

Builders should optimize chunk construction to minimize cross-chunk state dependencies:

```python
def optimize_chunks_for_state_access(
    transactions: List[Transaction]
) -> List[List[Transaction]]:
    """
    Group transactions to minimize state contention between chunks
    """
    # Analyze transaction state access patterns
    access_graph = build_state_access_graph(transactions)
    
    # Cluster transactions that access similar state
    clusters = cluster_by_state_access(access_graph)
    
    # Pack clusters into chunks
    optimized_chunks = []
    for cluster in clusters:
        if fits_in_chunk(cluster):
            optimized_chunks.append(cluster)
        else:
            # Split large clusters
            split_clusters = split_cluster_for_chunks(cluster)
            optimized_chunks.extend(split_clusters)
    
    return optimized_chunks
```

### CAL generation

#### Efficient CAL construction

```python
def generate_cal_for_chunk(
    chunk: ExecutionChunk,
    chunk_index: uint8,
    pre_state: StateDB
) -> ChunkAccessList:
    """
    Generate minimal CAL for chunk execution
    """
    # Track state changes during execution
    state_tracker = StateChangeTracker(pre_state)
    
    # Execute chunk transactions
    for tx_index, tx in enumerate(chunk.transactions):
        # Execute and track changes
        result = execute_transaction(tx, state_tracker)
        
        # Record state diffs
        for address in result.accessed_addresses:
            # Track storage changes
            for slot in result.storage_changes[address]:
                state_tracker.record_storage_change(
                    tx_index,
                    address,
                    slot,
                    result.storage_values[address][slot]
                )
            
            # Track balance changes
            if result.balance_changed[address]:
                state_tracker.record_balance_change(
                    tx_index,
                    address,
                    result.balances[address]
                )
            
            # Track nonce changes
            if result.nonce_changed[address]:
                state_tracker.record_nonce_change(
                    tx_index,
                    address,
                    result.nonces[address]
                )
            
            # Track code changes
            if result.code_changed[address]:
                state_tracker.record_code_change(
                    tx_index,
                    address,
                    result.codes[address]
                )
    
    # Encode state changes as CAL
    cal = encode_state_changes_as_cal(state_tracker.get_changes())
    
    return cal
```

### Publishing strategy

#### Optimal chunk and CAL publishing

```python
def publish_chunks_optimally(
    block: BeaconBlock,
    chunks: List[ExecutionChunk],
    cals: List[ChunkAccessList]
) -> None:
    """
    Publish chunks and CALs for optimal propagation
    """
    block_root = compute_block_root(block)
    
    # Phase 1: Publish chunks immediately
    publish_chunks_parallel(block_root, chunks)
    
    # Phase 2: Generate and publish CALs as chunks execute
    for i, cal in enumerate(cals):
        # Ensure chunk i is executed before publishing CAL
        wait_for_chunk_execution(i)
        
        # Publish CAL for chunk i
        publish_cal(block_root, i, cal)
        
        # This enables chunk i+1 to be executed
        signal_cal_available(i)
```

### Builder selection

#### Modified builder selection with chunks

The builder selection process considers chunking capabilities:

```python
def select_builder_for_slot(
    slot: Slot,
    builders: List[BuilderInfo]
) -> ValidatorIndex:
    """
    Select builder considering chunking performance
    """
    eligible_builders = []
    
    for builder in builders:
        # Check builder supports EIP9999
        if not builder.supports_chunking:
            continue
        
        # Check builder's chunk delivery performance
        if builder.chunk_delivery_rate < MIN_CHUNK_DELIVERY_RATE:
            continue
        
        # Check builder's CAL generation speed
        if builder.avg_cal_generation_time > MAX_CAL_GENERATION_TIME:
            continue
        
        eligible_builders.append(builder)
    
    # Select based on bid value and reliability
    return select_best_builder(eligible_builders)
```

## Builder penalties

### Chunking violations

Builders face penalties for:

```python
def check_builder_violations(
    builder: ValidatorIndex,
    bid: ExecutionPayloadBid,
    chunks: List[ExecutionChunk],
    cals: List[ChunkAccessList]
) -> List[Violation]:
    """
    Check for builder chunking violations
    """
    violations = []
    
    # Check chunk commitments match
    for i, chunk in enumerate(chunks):
        if compute_chunk_root(chunk) != bid.chunk_roots[i]:
            violations.append(ChunkCommitmentViolation(builder, i))
    
    # Check CAL commitments match
    for i, cal in enumerate(cals):
        if compute_cal_root(cal) != bid.chunk_access_list_roots[i]:
            violations.append(CALCommitmentViolation(builder, i))
    
    # Check chunk gas limits
    for chunk in chunks:
        if chunk.chunk_header.gas_used > CHUNK_GAS_LIMIT:
            violations.append(ChunkGasViolation(builder, chunk.chunk_header.index))
    
    # Check fill ratios
    if not validate_chunk_fill_ratio(chunks):
        violations.append(ChunkFillViolation(builder))
    
    return violations
```

### Availability failures

```python
def penalize_builder_unavailability(
    builder: ValidatorIndex,
    missing_chunks: List[uint8],
    missing_cals: List[uint8]
) -> Gwei:
    """
    Calculate penalty for missing chunks/CALs
    """
    penalty = Gwei(0)
    
    # Penalty for missing chunks (severe)
    for chunk_index in missing_chunks:
        penalty += MISSING_CHUNK_PENALTY
    
    # Penalty for missing CALs (moderate)
    for cal_index in missing_cals:
        penalty += MISSING_CAL_PENALTY
    
    return penalty
```

## MEV considerations

### Cross-chunk MEV

Builders must consider MEV opportunities across chunk boundaries:

```python
def optimize_mev_across_chunks(
    transactions: List[Transaction],
    chunk_boundaries: List[int]
) -> List[List[Transaction]]:
    """
    Optimize transaction ordering for MEV across chunks
    """
    # Identify MEV opportunities
    mev_bundles = identify_mev_bundles(transactions)
    
    # Ensure atomic bundles don't span chunks
    adjusted_chunks = []
    for bundle in mev_bundles:
        if spans_multiple_chunks(bundle, chunk_boundaries):
            # Reorganize to keep bundle atomic
            adjusted_chunks = move_bundle_to_single_chunk(bundle, chunk_boundaries)
    
    return adjusted_chunks
```

### CAL-aware MEV extraction

```python
def extract_mev_with_cals(
    chunks: List[ExecutionChunk],
    cals: List[ChunkAccessList]
) -> Gwei:
    """
    Calculate MEV considering CAL dependencies
    """
    total_mev = Gwei(0)
    
    for i, chunk in enumerate(chunks):
        # Calculate MEV for chunk
        chunk_mev = calculate_chunk_mev(chunk)
        
        # Adjust for CAL overhead
        if i > 0:
            # Later chunks have CAL dependency cost
            cal_cost = estimate_cal_propagation_cost(cals[i-1])
            chunk_mev -= cal_cost
        
        total_mev += max(0, chunk_mev)
    
    return total_mev
```

## Performance requirements

### Chunk generation latency

| Metric | Requirement |
| - | - |
| Chunk generation time | < 100ms per chunk |
| CAL generation time | < 50ms per CAL |
| Total bid preparation | < 2 seconds |
| Chunk publication | < 500ms after block |
| CAL publication | < 100ms after chunk execution |

### Resource requirements

| Resource | Requirement |
| - | - |
| Memory per chunk | < 256 MB |
| CPU cores | ≥ 8 cores for parallel execution |
| Network bandwidth | ≥ 1 Gbps for chunk distribution |
| Storage IOPS | ≥ 10,000 for CAL generation |