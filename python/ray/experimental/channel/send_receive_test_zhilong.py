# Import necessary libraries
import ray

from ray.dag import InputNode
from ray.experimental.channel.torch_tensor_type import TorchTensorType
import os
os.environ['ASCEND_RT_VISIBLE_DEVICES'] = "1,2,3"
# Define a remote worker class for tensor operations on NPUs
@ray.remote(resources={"NPU": 1})
class TorchTensorWorker:
    def __init__(self, rank):
        import torch
        os.environ['ASCEND_RT_VISIBLE_DEVICES'] = "1,2,3"
        import torch_npu
        # Initialize the worker on the specified NPU
        self.rank = rank
        torch_npu.npu.set_device(rank)


    def send(self, shape, dtype, value: int):
        import torch
        # Create and return a tensor filled with 'value' on the current NPU
        os.environ['ASCEND_RT_VISIBLE_DEVICES'] = "1,2,3"
        import torch_npu
        torch_npu.npu.set_device(self.rank)
        tmp = torch.ones(shape, dtype=dtype) * value
        return tmp.to(f"npu:1")

    def recv(self, tensor):
        # Verify the tensor is on the correct device and return it as CPU tensor
        return tensor.cpu()

# Initialize Ray
ray.init(address='10.170.23.167:6274')  # Initialize Ray


actor_cls = TorchTensorWorker
sender = actor_cls.remote(1)
receiver = actor_cls.remote(2)
import torch
shape = (10,)
dtype = torch.float16

# Test torch.Tensor sent between actors.
with InputNode() as inp:
    dag = sender.send.bind(shape, dtype, inp)
    # TODO(swang): Test that we are using the minimum number of
    # channels/messages when _direct_return=True.
    dag = dag.with_type_hint(TorchTensorType(shape, dtype, transport="nccl", _direct_return=True))
    dag = receiver.recv.bind(dag)

compiled_dag = dag.experimental_compile()
for i in range(3):
    ref = compiled_dag.execute(i)
    result = ray.get(ref)
    assert result == (i, shape, dtype)

compiled_dag.teardown()