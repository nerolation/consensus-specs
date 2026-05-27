# EIP-8146 -- The Beacon Chain

*Note*: This document is a work-in-progress for researchers and implementers.

## Table of contents

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Preset](#preset)
  - [Block access list](#block-access-list)
- [Containers](#containers)
  - [Modified `ExecutionPayload`](#modified-executionpayload)
  - [Modified `ExecutionPayloadBid`](#modified-executionpayloadbid)
  - [Modified `PayloadAttestationData`](#modified-payloadattestationdata)
  - [New `BlockAccessListSidecar`](#new-blockaccesslistsidecar)
- [Helpers](#helpers)
  - [`keccak256`](#keccak256)

<!-- mdformat-toc end -->

## Introduction

EIP-8146 moves the [EIP-7928](https://eips.ethereum.org/EIPS/eip-7928) block
access list (BAL) out of the `ExecutionPayload` and propagates it as an
independent sidecar. The builder commits to the BAL exactly once, in the bid,
using the same `keccak256(rlp(BAL))` value that EIP-7928 already defines as
`block_access_list_hash` in the EL block header. The CL holds the BAL as
opaque bytes and never RLP-decodes it.

*Note*: This specification is built upon
[Gloas](../../gloas/beacon-chain.md).

## Custom types

| Name              | SSZ equivalent                         | Description                              |
| ----------------- | -------------------------------------- | ---------------------------------------- |
| `BlockAccessList` | `ByteList[MAX_BLOCK_ACCESS_LIST_SIZE]` | RLP-encoded block access list (opaque to the CL) |

## Preset

### Block access list

| Name                         | Value                         |
| ---------------------------- | ----------------------------- |
| `MAX_BLOCK_ACCESS_LIST_SIZE` | `uint64(2**23)` (= 8,388,608) |

## Containers

### Modified `ExecutionPayload`

*Note*: The `block_access_list` field added in Gloas is removed.

```python
class ExecutionPayload(Container):
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
    transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
    withdrawals: List[Withdrawal, MAX_WITHDRAWALS_PER_PAYLOAD]
    blob_gas_used: uint64
    excess_blob_gas: uint64
    slot_number: uint64
    # Removed `block_access_list`
```

### Modified `ExecutionPayloadBid`

*Note*: A `block_access_list_hash` field is added. Its value is identical to
the EL header `block_access_list_hash` defined by EIP-7928, so no second
commitment scheme is introduced.

```python
class ExecutionPayloadBid(Container):
    parent_block_hash: Hash32
    parent_block_root: Root
    block_hash: Hash32
    prev_randao: Bytes32
    fee_recipient: ExecutionAddress
    gas_limit: uint64
    builder_index: BuilderIndex
    slot: Slot
    value: Gwei
    execution_payment: Gwei
    blob_kzg_commitments: List[KZGCommitment, MAX_BLOB_COMMITMENTS_PER_BLOCK]
    execution_requests_root: Root
    # [New in EIP8146]
    block_access_list_hash: Hash32
```

### Modified `PayloadAttestationData`

```python
class PayloadAttestationData(Container):
    beacon_block_root: Root
    slot: Slot
    payload_present: boolean
    blob_data_available: boolean
    # [New in EIP8146]
    block_access_list_present: boolean
```

### New `BlockAccessListSidecar`

```python
class BlockAccessListSidecar(Container):
    beacon_block_root: Root
    slot: Slot
    block_access_list: BlockAccessList
```

## Helpers

### `keccak256`

*Note*: `keccak256` is the Keccak-256 hash function used by EIP-7928 to
compute `block_access_list_hash`. It is distinct from the SHA-256 used by
SSZ. Implementations import it from an existing dependency (e.g. `eth_hash`,
`pycryptodome`).

```python
def keccak256(data: bytes) -> Bytes32:
    """Keccak-256 of ``data`` (FIPS 202 Keccak, as used by EIP-7928)."""
    ...
```
