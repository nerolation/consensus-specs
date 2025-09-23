# Payload Chunking -- Networking

*Note*: This document is a work-in-progress for researchers and implementers.

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Configuration](#configuration)
- [Containers](#containers)
- [The gossip domain: gossipsub](#the-gossip-domainion-gossipsub)
  - [Topics and messages](#topics-and-messages)
    - [Global topics](#global-topics)
      - [`beacon_block`](#beacon_block)
    - [Chunk subnets](#chunk-subnets)
      - [`execution_chunk_sidecar_{subnet_id}`](#execution_chunk_sidecar_subnet_id)
    - [Chunk access list subnets](#chunk-access-list-subnets)
      - [`chunk_access_list_sidecar_{subnet_id}`](#chunk_access_list_sidecar_subnet_id)
- [The Req/Resp domain](#the-reqresp-domain)
  - [Messages](#messages)
    - [`ExecutionChunkSidecarsByRoot`](#executionchunksidecarsbyroot)
    - [`ExecutionChunkSidecarsByRange`](#executionchunksidecarsbyrange)
    - [`ChunkAccessListSidecarsByRoot`](#chunkaccesslistsidecarsbyroot)
    - [`ChunkAccessListSidecarsByRange`](#chunkaccesslistsidecarsbyrange)

<!-- mdformat-toc end -->

## Introduction

This document specifies the networking layer for payload chunking, building upon [Gloas networking](../../gloas/p2p-interface.md).

## Configuration

| Name | Value | Description |
| ---- | ----- | ----------- |
| `EXECUTION_CHUNK_SUBNET_COUNT` | `8` | Number of execution chunk subnets |
| `CHUNK_ACCESS_LIST_SUBNET_COUNT` | `4` | Number of chunk access list subnets |
| `MAX_REQUEST_CHUNKS` | `128` | Maximum chunks in a single request |

## Containers

The containers are defined in [the beacon chain specification](./beacon-chain.md).

## The gossip domain: gossipsub

### Topics and messages

The new topics along with the type of the `data` field of a gossipsub message are:

| Name | Message Type |
| ---- | ------------ |
| `execution_chunk_sidecar_{subnet_id}` | `ExecutionChunkSidecar` |
| `chunk_access_list_sidecar_{subnet_id}` | `ChunkAccessListSidecar` |

The following existing topics are modified:

| Name | Message Type |
| ---- | ------------ |
| `beacon_block` | `SignedBeaconBlock` (modified to include chunk_roots and chunk_access_list_roots) |

#### Global topics

##### `beacon_block`

The beacon block is modified to include commitments to chunks and chunk access lists.

Modified validations:

- _[REJECT]_ The block contains valid chunk_roots -- i.e. `len(block.message.body.chunk_roots) > 0` and `len(block.message.body.chunk_roots) <= MAX_CHUNKS_PER_BLOCK`
- _[REJECT]_ The block contains matching chunk_access_list_roots -- i.e. `len(block.message.body.chunk_access_list_roots) == len(block.message.body.chunk_roots)`

#### Chunk subnets

##### `execution_chunk_sidecar_{subnet_id}`

This topic is used to propagate execution chunk sidecars, where each chunk index maps to some `subnet_id`.

```python
def compute_subnet_for_chunk_sidecar(chunk_index: uint64) -> uint64:
    return chunk_index % EXECUTION_CHUNK_SUBNET_COUNT
```

The following validations MUST pass before forwarding the `chunk_sidecar` on the network, assuming the alias `block_header = chunk_sidecar.signed_block_header.message`:

- _[REJECT]_ The sidecar's index is consistent with `MAX_CHUNKS_PER_BLOCK` -- i.e. `chunk_sidecar.index < MAX_CHUNKS_PER_BLOCK`
- _[REJECT]_ The sidecar is for the correct subnet -- i.e. `compute_subnet_for_chunk_sidecar(chunk_sidecar.index) == subnet_id`
- _[IGNORE]_ The sidecar is not from a future slot (with a `MAXIMUM_GOSSIP_CLOCK_DISPARITY` allowance) -- i.e. validate that `block_header.slot <= current_slot`
- _[IGNORE]_ The sidecar is from a slot greater than the latest finalized slot -- i.e. validate that `block_header.slot > compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)`
- _[REJECT]_ The proposer signature of `chunk_sidecar.signed_block_header` is valid with respect to the `block_header.proposer_index` pubkey
- _[IGNORE]_ The sidecar's block's parent (defined by `block_header.parent_root`) has been seen
- _[REJECT]_ The sidecar's block's parent (defined by `block_header.parent_root`) passes validation
- _[REJECT]_ The sidecar is from a higher slot than the sidecar's block's parent
- _[REJECT]_ The current finalized_checkpoint is an ancestor of the sidecar's block -- i.e. `get_checkpoint_block(store, block_header.parent_root, store.finalized_checkpoint.epoch) == store.finalized_checkpoint.root`
- _[REJECT]_ The sidecar's inclusion proof is valid as verified by `verify_chunk_inclusion_proof(chunk_sidecar)`
- _[REJECT]_ The chunk respects the gas limit -- i.e. `chunk_sidecar.chunk.gas_used <= CHUNK_GAS_LIMIT`
- _[REJECT]_ The chunk index matches -- i.e. `chunk_sidecar.chunk.index == chunk_sidecar.index`
- _[REJECT]_ For non-last chunks, verify no withdrawals -- i.e. if `chunk_sidecar.index < len(beacon_block.body.chunk_roots) - 1`, then `len(chunk_sidecar.chunk.withdrawals) == 0`
- _[REJECT]_ For the last chunk, verify withdrawals are present (unless none expected) -- i.e. if `chunk_sidecar.index == len(beacon_block.body.chunk_roots) - 1`, then `len(chunk_sidecar.chunk.withdrawals) > 0` or `get_expected_withdrawals(state) == []`
- _[IGNORE]_ The sidecar is the first sidecar for the tuple `(block_header.slot, block_header.proposer_index, chunk_sidecar.index)` with valid header signature and inclusion proof
- _[REJECT]_ The sidecar is proposed by the expected `proposer_index` for the block's slot

#### Chunk access list subnets  

##### `chunk_access_list_sidecar_{subnet_id}`

This topic is used to propagate chunk access list sidecars, where each chunk access list index maps to some `subnet_id`.

```python
def compute_subnet_for_chunk_access_list_sidecar(cal_index: uint64) -> uint64:
    return cal_index % CHUNK_ACCESS_LIST_SUBNET_COUNT
```

The following validations MUST pass before forwarding the `cal_sidecar` on the network, assuming the alias `block_header = cal_sidecar.signed_block_header.message`:

- _[REJECT]_ The sidecar's index is consistent with `MAX_CHUNKS_PER_BLOCK` -- i.e. `cal_sidecar.index < MAX_CHUNKS_PER_BLOCK`
- _[REJECT]_ The sidecar is for the correct subnet -- i.e. `compute_subnet_for_chunk_access_list_sidecar(cal_sidecar.index) == subnet_id`
- _[IGNORE]_ The sidecar is not from a future slot (with a `MAXIMUM_GOSSIP_CLOCK_DISPARITY` allowance) -- i.e. validate that `block_header.slot <= current_slot`
- _[IGNORE]_ The sidecar is from a slot greater than the latest finalized slot -- i.e. validate that `block_header.slot > compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)`
- _[REJECT]_ The proposer signature of `cal_sidecar.signed_block_header` is valid with respect to the `block_header.proposer_index` pubkey
- _[IGNORE]_ The sidecar's block's parent (defined by `block_header.parent_root`) has been seen
- _[REJECT]_ The sidecar's block's parent (defined by `block_header.parent_root`) passes validation
- _[REJECT]_ The sidecar is from a higher slot than the sidecar's block's parent
- _[REJECT]_ The current finalized_checkpoint is an ancestor of the sidecar's block -- i.e. `get_checkpoint_block(store, block_header.parent_root, store.finalized_checkpoint.epoch) == store.finalized_checkpoint.root`
- _[REJECT]_ The sidecar's inclusion proof is valid as verified by `verify_chunk_access_list_inclusion_proof(cal_sidecar)`
- _[IGNORE]_ The sidecar is the first sidecar for the tuple `(block_header.slot, block_header.proposer_index, cal_sidecar.index)` with valid header signature and inclusion proof
- _[REJECT]_ The sidecar is proposed by the expected `proposer_index` for the block's slot

## The Req/Resp domain

### Messages

#### `ExecutionChunkSidecarsByRoot`

**Protocol ID:** `/eth2/beacon_chain/req/execution_chunk_sidecars_by_root/1/`

Request and Response remain unchanged from the blob sidecars pattern. This is a `v1` request.

Request Content:
```python
class ExecutionChunkSidecarsByRootRequest(Container):
    chunk_ids: List[ChunkIdentifier, MAX_REQUEST_CHUNKS]

class ChunkIdentifier(Container):
    block_root: Root
    index: uint64
```

Response Content:
```python
List[ExecutionChunkSidecar, MAX_REQUEST_CHUNKS]
```

#### `ExecutionChunkSidecarsByRange`

**Protocol ID:** `/eth2/beacon_chain/req/execution_chunk_sidecars_by_range/1/`

Request Content:
```python  
class ExecutionChunkSidecarsByRangeRequest(Container):
    start_slot: Slot
    count: uint64
```

Response Content:
```python
List[ExecutionChunkSidecar, MAX_CHUNKS_PER_BLOCK * count]
```


#### `ChunkAccessListSidecarsByRoot`

**Protocol ID:** `/eth2/beacon_chain/req/chunk_access_list_sidecars_by_root/1/`

Request Content:
```python
class ChunkAccessListSidecarsByRootRequest(Container):
    cal_ids: List[ChunkAccessListIdentifier, MAX_REQUEST_CHUNK_ACCESS_LISTS]

class ChunkAccessListIdentifier(Container):
    block_root: Root
    index: uint64
```

Response Content:
```python
List[ChunkAccessListSidecar, MAX_REQUEST_CHUNK_ACCESS_LISTS]
```

#### `ChunkAccessListSidecarsByRange`

**Protocol ID:** `/eth2/beacon_chain/req/chunk_access_list_sidecars_by_range/1/`

Request Content:
```python
class ChunkAccessListSidecarsByRangeRequest(Container):
    start_slot: Slot
    count: uint64
```

Response Content:
```python
List[ChunkAccessListSidecar, MAX_CHUNKS_PER_BLOCK * count]
```

