from ..constants import EIP8146
from .base import BaseSpecBuilder


class EIP8146SpecBuilder(BaseSpecBuilder):
    fork: str = EIP8146

    @classmethod
    def imports(cls, preset_name: str):
        return f"""
from eth_consensus_specs.gloas import {preset_name} as gloas
"""

    @classmethod
    def sundry_functions(cls) -> str:
        return """
def keccak256(data: bytes) -> Bytes32:
    # pylint: disable=import-outside-toplevel
    from eth_hash.auto import keccak
    return Bytes32(keccak(data))
"""

    @classmethod
    def execution_engine_cls(cls) -> str:
        return """
class NoopExecutionEngine(ExecutionEngine):

    def notify_new_payload(self: ExecutionEngine,
                           execution_payload: ExecutionPayload,
                           parent_beacon_block_root: Root,
                           execution_requests_list: Sequence[bytes]) -> bool:
        return True

    def notify_forkchoice_updated(self: ExecutionEngine,
                                  head_block_hash: Hash32,
                                  safe_block_hash: Hash32,
                                  finalized_block_hash: Hash32,
                                  payload_attributes: Optional[PayloadAttributes]) -> Optional[PayloadId]:
        pass

    def get_payload(self: ExecutionEngine, payload_id: PayloadId) -> GetPayloadResponse:
        # pylint: disable=unused-argument
        raise NotImplementedError("no default block production")

    def is_valid_block_hash(self: ExecutionEngine,
                            execution_payload: ExecutionPayload,
                            parent_beacon_block_root: Root,
                            execution_requests_list: Sequence[bytes]) -> bool:
        return True

    def is_valid_versioned_hashes(self: ExecutionEngine, new_payload_request: NewPayloadRequest) -> bool:
        return True

    def verify_and_notify_new_payload(self: ExecutionEngine,
                                      new_payload_request: NewPayloadRequest) -> bool:
        return True

    def notify_block_access_list(self: ExecutionEngine,
                                 block_hash: Hash32,
                                 block_access_list: BlockAccessList) -> None:
        # pylint: disable=unused-argument
        return None


EXECUTION_ENGINE = NoopExecutionEngine()"""
