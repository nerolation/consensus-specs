# EIP-9999 -- Builder Specification

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document specifies builder behavior for EIP-9999 Payload Chunking in the context of enshrined Proposer-Builder Separation (ePBS) from Gloas.

## Builder responsibilities

### Payload construction

#### Chunked payload assembly

Builders must:
1. Order transactions for optimal chunking
2. Split transactions into chunks respecting `CHUNK_GAS_LIMIT`
3. Ensure non-terminal chunks meet `MIN_CHUNK_FILL_RATIO`
4. Maintain parent chunk hash chain:
   - First chunk points to previous slot's last chunk hash
   - Subsequent chunks point to previous chunk hash
5. Place withdrawals only in the final chunk

### Bid construction

#### Creating execution payload bid with chunks

Bids must include:
- `chunk_roots`: Commitments to each chunk
- `chunk_access_list_roots`: Commitments to each CAL
- Standard bid fields (value, state_root, etc.)

### Chunk optimization

#### State access optimization

Builders should:
- Group transactions accessing similar state into same chunks
- Minimize cross-chunk state dependencies
- Cluster transactions by access patterns

### CAL generation

#### Efficient CAL construction

CALs must contain:
- State diffs from chunk execution
- Account balance/nonce/code changes
- Storage slot modifications
- Minimal representation within `MAX_CHUNK_ACCESS_LIST_SIZE`

### Publishing strategy

#### Optimal chunk and CAL publishing

Publishing order:
1. Publish chunks immediately after block
2. Generate and publish CALs as chunks execute
3. Enable cascading execution by timely CAL release

### Builder selection

#### Modified builder selection with chunks

Selection criteria include:
- EIP9999 support capability
- Chunk delivery performance (`MIN_CHUNK_DELIVERY_RATE`)
- CAL generation speed (`MAX_CAL_GENERATION_TIME`)
- Bid value and reliability

## Builder penalties

### Chunking violations

Builders face penalties for:
- Chunk commitments not matching published chunks
- CAL commitments not matching generated CALs
- Chunks exceeding `CHUNK_GAS_LIMIT`
- Violating fill ratio requirements

### Availability failures

Penalties apply for:
- Missing chunks: `MISSING_CHUNK_PENALTY` per chunk
- Missing CALs: `MISSING_CAL_PENALTY` per CAL
- Late publication beyond deadlines

## MEV considerations

### Cross-chunk MEV

Builders must:
- Keep atomic MEV bundles within single chunks
- Avoid splitting dependent transactions across chunks
- Consider CAL overhead in MEV calculations

### CAL-aware MEV extraction

MEV extraction considers:
- CAL propagation costs for later chunks
- State contention between chunks
- Atomic bundle requirements

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