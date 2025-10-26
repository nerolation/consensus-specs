# EIP-9999 -- Fork Logic

**Notice**: This document is a work-in-progress for researchers and implementers.

## Introduction

This document describes the process of activating EIP-9999 Payload Chunking on top of Gloas.

## Configuration

| Name | Value |
| - | - |
| `EIP9999_FORK_VERSION` | `Version('0x09999000')` |
| `EIP9999_FORK_EPOCH` | `Epoch(18446744073709551615)` **TBD** |

## Fork to EIP-9999

### Fork trigger

EIP-9999 is activated as a feature on top of the Gloas fork at epoch `EIP9999_FORK_EPOCH`.

Note: The `EIP9999_FORK_EPOCH` must be set to an epoch after `GLOAS_FORK_EPOCH`.

### Upgrading the state

If `state.slot % SLOTS_PER_EPOCH == 0` and `compute_epoch_at_slot(state.slot) == EIP9999_FORK_EPOCH`, 
an irregular state change is made to upgrade to EIP-9999.

```python
def upgrade_to_eip9999(pre: gloas.BeaconState) -> BeaconState:
    epoch = gloas.get_current_epoch(pre)
    
    # Update ExecutionPayloadBid to include chunking fields
    upgraded_bid = ExecutionPayloadBid(
        builder=pre.latest_execution_payload_bid.builder,
        value=pre.latest_execution_payload_bid.value,
        kzg_commitments_root=pre.latest_execution_payload_bid.kzg_commitments_root,
        state_root=pre.latest_execution_payload_bid.state_root,
        parent_hash=pre.latest_execution_payload_bid.parent_hash,
        builder_hash=pre.latest_execution_payload_bid.builder_hash,
        withdrawals_root=pre.latest_execution_payload_bid.withdrawals_root,
        # New chunking fields
        chunk_roots=List[Root, MAX_CHUNKS_PER_BLOCK](),
        chunk_access_list_roots=List[Root, MAX_CHUNKS_PER_BLOCK]()
    )
    
    post = BeaconState(
        # Versioning
        genesis_time=pre.genesis_time,
        genesis_validators_root=pre.genesis_validators_root,
        slot=pre.slot,
        fork=Fork(
            previous_version=pre.fork.current_version,
            current_version=EIP9999_FORK_VERSION,  # [Modified in EIP9999]
            epoch=epoch,
        ),
        # History
        latest_block_header=pre.latest_block_header,
        block_roots=pre.block_roots,
        state_roots=pre.state_roots,
        historical_roots=pre.historical_roots,
        # Eth1
        eth1_data=pre.eth1_data,
        eth1_data_votes=pre.eth1_data_votes,
        eth1_deposit_index=pre.eth1_deposit_index,
        # Registry
        validators=pre.validators,
        balances=pre.balances,
        # Randomness
        randao_mixes=pre.randao_mixes,
        # Slashings
        slashings=pre.slashings,
        # Participation
        previous_epoch_participation=pre.previous_epoch_participation,
        current_epoch_participation=pre.current_epoch_participation,
        # Finality
        justification_bits=pre.justification_bits,
        previous_justified_checkpoint=pre.previous_justified_checkpoint,
        current_justified_checkpoint=pre.current_justified_checkpoint,
        finalized_checkpoint=pre.finalized_checkpoint,
        # Inactivity
        inactivity_scores=pre.inactivity_scores,
        # Sync
        current_sync_committee=pre.current_sync_committee,
        next_sync_committee=pre.next_sync_committee,
        # Gloas
        latest_execution_payload_bid=upgraded_bid,  # [Modified in EIP9999]
        next_withdrawal_index=pre.next_withdrawal_index,
        next_withdrawal_validator_index=pre.next_withdrawal_validator_index,
        historical_summaries=pre.historical_summaries,
        deposit_requests_start_index=pre.deposit_requests_start_index,
        deposit_balance_to_consume=pre.deposit_balance_to_consume,
        exit_balance_to_consume=pre.exit_balance_to_consume,
        earliest_exit_epoch=pre.earliest_exit_epoch,
        consolidation_balance_to_consume=pre.consolidation_balance_to_consume,
        earliest_consolidation_epoch=pre.earliest_consolidation_epoch,
        pending_deposits=pre.pending_deposits,
        pending_partial_withdrawals=pre.pending_partial_withdrawals,
        pending_consolidations=pre.pending_consolidations,
        proposer_lookahead=pre.proposer_lookahead,
        execution_payload_availability=pre.execution_payload_availability,
        builder_pending_payments=pre.builder_pending_payments,
        builder_pending_withdrawals=pre.builder_pending_withdrawals,
        latest_withdrawals_root=pre.latest_withdrawals_root,
        # New chunking fields [New in EIP9999]
        latest_chunk_hash=pre.latest_block_hash,  # Convert: last block hash becomes first parent chunk hash
        chunk_execution_status=List[ChunkExecutionResult, MAX_CHUNKS_PER_BLOCK](),
        received_chunk_indices=Bitvector[MAX_CHUNKS_PER_BLOCK](),
        received_cal_indices=Bitvector[MAX_CHUNKS_PER_BLOCK]()
    )
    
    return post
```

### Fork-specific helper functions

#### `is_eip9999_fork`

```python
def is_eip9999_fork(state: BeaconState) -> bool:
    """
    Check if the state is post-EIP9999 fork
    """
    return state.fork.current_version == EIP9999_FORK_VERSION
```

#### `get_eip9999_fork_epoch`

```python
def get_eip9999_fork_epoch() -> Epoch:
    """
    Return the epoch at which EIP9999 activates
    """
    return EIP9999_FORK_EPOCH
```