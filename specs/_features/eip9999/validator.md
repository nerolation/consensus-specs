# EIP-9999 -- Honest Validator

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document represents the changes to the honest validator guide for EIP-9999 Payload Chunking, extending the Gloas validator responsibilities.

## Prerequisites

This document extends the [Gloas Honest Validator](../../gloas/validator.md) guide. All existing Gloas responsibilities remain unless explicitly modified here.

## Beacon chain responsibilities

### Attestation

#### Modified attestation timing

Validators must wait for chunk availability before attesting. The attestation index depends on:
- 0: No chunks available or timeout reached
- 1: All chunks and CALs available for full validation

#### Attestation deadlines

| Name | Value | Description |
| - | - | - |
| `ATTESTATION_DEADLINE_PARTIAL_CHUNKS` | `uint64(3000)` | 3 seconds - deadline when chunks partially available |
| `ATTESTATION_DEADLINE_MISSING_CALS` | `uint64(4000)` | 4 seconds - deadline when chunks available but CALs missing |

### Block proposal

#### Constructing execution payload with chunks

When proposing with EIP9999 active, proposers must:
1. Split execution payload into chunks respecting gas limits
2. Generate CALs during chunk execution  
3. Create bid with chunk and CAL commitments

#### Publishing chunks and CALs

Proposers/builders must:
1. Publish chunk sidecars immediately (can be before beacon block)
2. Use slot and proposer_index for identification
3. Route to appropriate subnets (`chunk_index % CHUNK_SUBNET_COUNT`)
4. Publish CALs as chunks execute (`cal_index % CAL_SUBNET_COUNT`)
5. Include valid proposer signatures

### Chunk and CAL validation

#### Chunk sidecar validation

Validate:
- Block reference exists
- Chunk index within bounds
- Inclusion proof against bid commitment
- Chunk structure (gas limits, transaction integrity)
- Builder signature

#### CAL sidecar validation

Validate:
- Block reference exists  
- CAL index within bounds
- Inclusion proof against bid commitment
- Size limit (`MAX_CHUNK_ACCESS_LIST_SIZE`)
- Builder signature

### Sync committee participation

Sync committee signatures require at least 50% chunk availability for EIP9999 blocks.

## Builder responsibilities

### Chunk construction rules

Builders must:
- Respect `CHUNK_GAS_LIMIT` per chunk
- Ensure non-terminal chunks meet `MIN_CHUNK_FILL_RATIO` or combined gas rule
- Place withdrawals only in the final chunk
- Maintain parent chunk hash chain

### CAL generation

Builders generate CALs containing state diffs from chunk execution.

## Slashing conditions

### Invalid chunk construction

Builders can be slashed for:
- Publishing chunks violating gas limits
- Publishing chunks not matching committed roots
- Publishing invalid CALs not matching chunk execution

### Withholding chunks or CALs

Builders can be penalized for:
- Failing to publish committed chunks within deadline
- Failing to publish CALs after chunks are published

## Incentives

### Chunk availability rewards

- Correct payload status attestations receive full rewards
- Incorrect payload status attestations receive reduced rewards
- Subnet hosting validators may receive priority fees

### Builder incentives

Builders incentivized to:
- Construct efficient chunks minimizing state contention
- Publish chunks and CALs quickly for validation
- Maintain high availability for distribution