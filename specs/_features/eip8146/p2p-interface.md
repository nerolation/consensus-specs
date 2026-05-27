# EIP-8146 -- Networking

This document contains the networking specifications for EIP-8146.

*Note*: This specification is built upon
[Gloas](../../gloas/p2p-interface.md).

## Table of contents

<!-- mdformat-toc start --slug=github --no-anchors --maxlevel=6 --minlevel=2 -->

- [Configuration](#configuration)
- [The gossip domain: gossipsub](#the-gossip-domain-gossipsub)
  - [Topics and messages](#topics-and-messages)
    - [Global topics](#global-topics)
      - [`block_access_list_sidecar`](#block_access_list_sidecar)
- [The Req/Resp domain](#the-reqresp-domain)
  - [Messages](#messages)
    - [BlockAccessListSidecarsByRoot v1](#blockaccesslistsidecarsbyroot-v1)
    - [BlockAccessListSidecarsByRange v1](#blockaccesslistsidecarsbyrange-v1)
- [Validator duties](#validator-duties)
  - [Builder: BAL sidecar publication](#builder-bal-sidecar-publication)
  - [PTC member: `block_access_list_present`](#ptc-member-block_access_list_present)

<!-- mdformat-toc end -->

## Configuration

| Name                                  | Value                    | Description                                                   |
| ------------------------------------- | ------------------------ | ------------------------------------------------------------- |
| `MIN_EPOCHS_FOR_BAL_SIDECAR_REQUESTS` | `2**12` (= 4,096 epochs) | Minimum epoch range over which a node must serve BAL sidecars |

## The gossip domain: gossipsub

### Topics and messages

#### Global topics

##### `block_access_list_sidecar`

Propagates `BlockAccessListSidecar` objects. The CL treats
`sidecar.block_access_list` as opaque bytes; no RLP decoding is performed.

The following validations MUST pass before forwarding a `sidecar`, with
`block` aliased to the beacon block at `sidecar.beacon_block_root` and
`bid = block.body.signed_execution_payload_bid.message`:

- _[IGNORE]_ The beacon block at `sidecar.beacon_block_root` has been seen
  (via gossip or non-gossip sources). A client MAY queue the sidecar for
  deferred processing once the block arrives.
- _[IGNORE]_ No valid `BlockAccessListSidecar` for `sidecar.beacon_block_root`
  has previously been seen.
- _[IGNORE]_ `sidecar.slot >= compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)`.
- _[REJECT]_ `sidecar.slot == block.slot`.
- _[REJECT]_ `keccak256(sidecar.block_access_list) == bid.block_access_list_hash`.

The maximum byte length is enforced by SSZ deserialization of
`ByteList[MAX_BLOCK_ACCESS_LIST_SIZE]`; no separate length check is required.

## The Req/Resp domain

### Messages

#### BlockAccessListSidecarsByRoot v1

**Protocol ID:** `/eth2/beacon_chain/req/block_access_list_sidecars_by_root/1/`

Request Content:

```
(
  List[Root, MAX_REQUEST_PAYLOADS]
)
```

Response Content:

```
(
  List[BlockAccessListSidecar, MAX_REQUEST_PAYLOADS]
)
```

Returns sidecars matching the requested `beacon_block_root` values. The
response MUST contain no more than `MAX_REQUEST_PAYLOADS` sidecars and MAY
contain fewer if the responder does not have them all.

Clients MUST support serving requests for any canonical block within the last
`MIN_EPOCHS_FOR_BAL_SIDECAR_REQUESTS` epochs. Peers unable to reply SHOULD
respond with error code `3: ResourceUnavailable`.

#### BlockAccessListSidecarsByRange v1

**Protocol ID:** `/eth2/beacon_chain/req/block_access_list_sidecars_by_range/1/`

Request Content:

```
(
  start_slot: Slot
  count: uint64
)
```

Response Content:

```
(
  List[BlockAccessListSidecar, MAX_REQUEST_PAYLOADS]
)
```

Returns sidecars in slot range `[start_slot, start_slot + count)`, ordered by
slot. Clients MUST support serving requests for slots within the last
`MIN_EPOCHS_FOR_BAL_SIDECAR_REQUESTS` epochs, on the canonical chain. Peers
unable to reply SHOULD respond with error code `3: ResourceUnavailable`.
No more than `MAX_REQUEST_PAYLOADS` sidecars may be returned per request.

## Validator duties

### Builder: BAL sidecar publication

When constructing a bid:

1. Call `engine_getPayloadV6`; receive `payload` and `blockAccessList`.
2. Set `bid.block_access_list_hash = keccak256(blockAccessList)`.
3. Sign and broadcast the bid on `execution_payload_bid`.

After the proposer publishes a `SignedBeaconBlock` referencing the bid:

4. Broadcast
   `BlockAccessListSidecar(beacon_block_root=hash_tree_root(block), slot=block.slot, block_access_list=blockAccessList)`
   on `block_access_list_sidecar`.
5. Broadcast the `SignedExecutionPayloadEnvelope` on `execution_payload`.

Builders SHOULD publish the BAL sidecar before the envelope so peers can
prefetch state during envelope propagation.

### PTC member: `block_access_list_present`

A PTC member sets `block_access_list_present = True` in its
`PayloadAttestationData` iff a valid `BlockAccessListSidecar` for the block
has been received locally by the attestation deadline; otherwise `False`.
The bit is set independently of `payload_present` and `blob_data_available`.
