import os
import torch
os.environ['ASCEND_RT_VISIBLE_DEVICES'] = "1,2,3"
import torch.distributed as dist
import torch_npu
from ray.experimental.channel.gpu_communicator import (
    GPUCommunicator,
    TorchTensorAllocator,
)
from typing import TYPE_CHECKING, List, Optional, Tuple


class _HCCLGroup(GPUCommunicator):
    def __init__(self, world_size: int, comm_id: int, rank: int, actor_handles: list, cuda_stream: Optional[int]):
        self._world_size = world_size
        self._comm_id = comm_id
        self._rank = rank
        self._actor_handles = actor_handles
        self._closed = False
        print(rank, world_size)
        if rank is not None:
            self._init_dist_hccl(rank, world_size)

    def _init_dist_hccl(self, rank, world_size):
        os.environ['MASTER_ADDR'] = '127.0.0.1'
        os.environ['MASTER_PORT'] = '29500'
        os.environ['HCCL_WHITELIST_DISABLE'] = '1'
        torch_npu.npu.set_device(rank)
        self.ctx = dist.init_process_group(backend='hccl', world_size=world_size, rank=rank)

    def initialize(self, rank: int) -> None:
        pass  # No additional initialization needed for HCCL group

    def get_actor_handles(self) -> list:
        return self._actor_handles

    def get_rank(self, actor: "ray.actor.ActorHandle") -> int:
        actor_ids = [a._ray_actor_id for a in self._actor_handles]
        try:
            rank = actor_ids.index(actor._ray_actor_id)
        except ValueError:
            raise ValueError("Actor is not in the HCCL group.")
        return rank

    def get_self_rank(self) -> int:
        return self._rank

    def get_world_size(self) -> int:
        return self._world_size

    def send(self, tensor: "torch.Tensor", peer_rank: int) -> None:
        if self._closed:
            raise RuntimeError("HCCL group has been destroyed.")
        print(tensor)
        dist.send(tensor, dst=peer_rank)

    def recv(self, shape: tuple, dtype: "torch.dtype", peer_rank: int,allocator=Optional[TorchTensorAllocator]) -> "torch.Tensor":
        if self._closed:
            raise RuntimeError("HCCL group has been destroyed.")
        torch_npu.npu.set_device(f"npu:2")
        tensor = torch.zeros(*shape, dtype=dtype).to(f"npu:2")
        dist.recv(tensor, src=peer_rank)
        print(tensor)
        return tensor

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        dist.destroy_process_group()