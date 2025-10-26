# EIP-9999 -- Networking

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document contains the consensus-layer networking specification for EIP-9999 Payload Chunking.

The specification extends the Gloas networking protocol with new topics and messages for chunk and CAL propagation.

## Configuration

### Chunk networking parameters

| Name | Value | Description |
| - | - | - |
| `CHUNK_SUBNET_COUNT` | `16` | Number of chunk subnets |
| `CAL_SUBNET_COUNT` | `16` | Number of CAL subnets |
| `MAX_REQUEST_CHUNKS` | `2**8` (256) | Maximum chunks in a single request |
| `MAX_REQUEST_CALS` | `2**8` (256) | Maximum CALs in a single request |
| `MAX_CHUNK_ACCESS_LIST_SIZE` | `2**20` (1 MB) | Maximum size of a CAL |

## The gossip domain: gossipsub

### Topics and messages

#### Global topics

The following topics are used for propagating chunks and CALs. These extend the existing Gloas topics.

##### `execution_chunk_sidecar_{subnet_id}`

This topic is used to propagate execution chunk sidecars.

- **Name**: `/eth2/` + `FORK_DIGEST` + `/execution_chunk_sidecar_` + `subnet_id` + `/ssz_snappy`
- **Subnet count**: `CHUNK_SUBNET_COUNT`
- **Subnet assignment**: `subnet_id = chunk_index % CHUNK_SUBNET_COUNT`

The `execution_chunk_sidecar_{subnet_id}` topic is used to propagate `ExecutionChunkSidecar` objects:

```python
class ExecutionChunkSidecar(Container):
    block_root: Root
    chunk_index: uint8
    chunk: ExecutionChunk
    chunk_signature: BLSSignature
    chunk_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```

Validation rules:
- The sidecar's `block_root` must reference a known beacon block
- The chunk index must be within bounds: `chunk_index < MAX_CHUNKS_PER_BLOCK`
- The subnet must match: `chunk_index % CHUNK_SUBNET_COUNT == subnet_id`
- The inclusion proof must be valid against the bid's chunk commitments
- The chunk structure must be valid (gas limits, transaction integrity)
- The chunk signature must be valid from the builder

Timing:
- Chunks MAY be published as soon as the beacon block is seen
- Chunks SHOULD be published within 2 seconds of the slot start
- Chunks MUST NOT be propagated more than `SECONDS_PER_SLOT` after the slot start

##### `chunk_access_list_sidecar_{subnet_id}`

- **Name**: `/eth2/` + `FORK_DIGEST` + `/chunk_access_list_sidecar_` + `subnet_id` + `/ssz_snappy`
- **Subnet count**: `CAL_SUBNET_COUNT`
- **Subnet assignment**: `subnet_id = cal_index % CAL_SUBNET_COUNT`

The `chunk_access_list_sidecar_{subnet_id}` topic is used to propagate `ChunkAccessListSidecar` objects:

```python
class ChunkAccessListSidecar(Container):
    block_root: Root
    chunk_index: uint8
    chunk_access_list: ChunkAccessList
    cal_signature: BLSSignature
    cal_root_inclusion_proof: Vector[Bytes32, CHUNK_INCLUSION_PROOF_DEPTH]
```

Validation rules:
- The sidecar's `block_root` must reference a known beacon block
- The chunk index must be within bounds: `chunk_index < MAX_CHUNKS_PER_BLOCK`
- The subnet must match: `chunk_index % CAL_SUBNET_COUNT == subnet_id`
- The inclusion proof must be valid against the bid's CAL commitments
- The CAL size must not exceed `MAX_CHUNK_ACCESS_LIST_SIZE`
- The CAL signature must be valid from the builder

Timing:
- CALs MAY be published as soon as the chunk is executed
- CALs SHOULD be published within 3 seconds of the slot start
- CALs MUST NOT be propagated more than `SECONDS_PER_SLOT` after the slot start

### Attestation subnets

#### Modified attestation validation

Attestations now consider chunk availability when determining payload status:

```python
def validate_attestation_with_chunks(attestation: Attestation, state: BeaconState) -> bool:
    """
    Validate attestation considering chunk availability
    """
    # Existing Gloas validation
    # ...
    
    # Check chunk availability if attesting to payload present
    if attestation.data.index == 1:  # Payload present
        block_root = attestation.data.beacon_block_root
        bid = get_bid_for_block(state, block_root)
        
        # Require at least one chunk to be available
        chunks_available = count_available_chunks(state, block_root)
        if chunks_available == 0:
            return False
    
    return True
```

## The Req/Resp domain

### Messages

#### ExecutionChunksByRange v1

**Protocol ID**: `/eth2/beacon_chain/req/execution_chunks_by_range/1/`

Request and Response schemas:

```python
class ExecutionChunksByRangeRequest(Container):
    start_slot: Slot
    count: uint64  # Number of slots
    chunk_indices: List[uint8, MAX_CHUNKS_PER_BLOCK]  # Which chunks to return
```

```python
class ExecutionChunksByRangeResponse(Container):
    chunks: List[ExecutionChunkSidecar, MAX_REQUEST_CHUNKS]
```

Request processing:
- Return chunks for the requested slots and indices
- Chunks must be returned in slot order, then by chunk index
- Skip slots where the requested chunks are not available
- The response MUST NOT exceed `MAX_REQUEST_CHUNKS` chunks

#### ExecutionChunksByRoot v1

**Protocol ID**: `/eth2/beacon_chain/req/execution_chunks_by_root/1/`

Request and Response schemas:

```python
class ExecutionChunksByRootRequest(Container):
    chunk_identifiers: List[ChunkIdentifier, MAX_REQUEST_CHUNKS]

class ChunkIdentifier(Container):
    block_root: Root
    chunk_index: uint8
```

```python
class ExecutionChunksByRootResponse(Container):
    chunks: List[ExecutionChunkSidecar, MAX_REQUEST_CHUNKS]
```

Request processing:
- Return the requested chunks identified by block root and index
- Chunks may be returned in any order
- Skip chunks that are not available
- The response MUST NOT exceed `MAX_REQUEST_CHUNKS` chunks

#### ChunkAccessListsByRange v1

**Protocol ID**: `/eth2/beacon_chain/req/chunk_access_lists_by_range/1/`

Request and Response schemas:

```python
class ChunkAccessListsByRangeRequest(Container):
    start_slot: Slot
    count: uint64  # Number of slots
    cal_indices: List[uint8, MAX_CHUNKS_PER_BLOCK]  # Which CALs to return
```

```python
class ChunkAccessListsByRangeResponse(Container):
    cals: List[ChunkAccessListSidecar, MAX_REQUEST_CALS]
```

Request processing:
- Return CALs for the requested slots and indices
- CALs must be returned in slot order, then by CAL index
- Skip slots where the requested CALs are not available
- The response MUST NOT exceed `MAX_REQUEST_CALS` CALs

#### ChunkAccessListsByRoot v1

**Protocol ID**: `/eth2/beacon_chain/req/chunk_access_lists_by_root/1/`

Request and Response schemas:

```python
class ChunkAccessListsByRootRequest(Container):
    cal_identifiers: List[CALIdentifier, MAX_REQUEST_CALS]

class CALIdentifier(Container):
    block_root: Root
    cal_index: uint8
```

```python
class ChunkAccessListsByRootResponse(Container):
    cals: List[ChunkAccessListSidecar, MAX_REQUEST_CALS]
```

Request processing:
- Return the requested CALs identified by block root and index
- CALs may be returned in any order
- Skip CALs that are not available
- The response MUST NOT exceed `MAX_REQUEST_CALS` CALs

### Discovery

#### Chunk and CAL availability

Nodes SHOULD advertise their chunk and CAL availability using ENR entries:

```python
# ENR key for chunk subnet subscription
CHUNK_SUBNET_ENR_KEY = "chnk"

# ENR key for CAL subnet subscription  
CAL_SUBNET_ENR_KEY = "cals"
```

The values are bitfields indicating which subnets the node is subscribed to:
- Bit `i` set to 1: node is subscribed to subnet `i`
- Bit `i` set to 0: node is not subscribed to subnet `i`

Full nodes SHOULD subscribe to all chunk and CAL subnets to ensure complete block availability.

### Rate limiting

The following rate limits apply to chunk and CAL requests:

| Protocol | Requests per minute | Burst |
| - | - | - |
| `execution_chunks_by_range` | 10 | 20 |
| `execution_chunks_by_root` | 20 | 40 |
| `chunk_access_lists_by_range` | 10 | 20 |
| `chunk_access_lists_by_root` | 20 | 40 |