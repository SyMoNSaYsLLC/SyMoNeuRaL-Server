# 4_DistributedComputing — Distributed computing

3 sample document(s), each with the verified *On this box* result and the complete upstream README.

> Part of the [SyMoNeuRaL documentation set](../README.md). Sliced from the consolidated manual at `../symoneural-manual.md`, which remains the canonical single file.

## 4_DistributedComputing — Distributed computing

Three samples. Note that only `simpleP2P` genuinely requires a second GPU — `ipcMemoryPool` is inter-process and runs fine here, and `multiGPUGradientAverage` runs with two oversubscribed MPI ranks.

<br>

### ipcMemoryPool

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
> python ipcMemoryPool.py
> ```
>
> **Result** — **Works on a single GPU.** IPC round-trip OK: parent created an IPC-enabled `DeviceMemoryResource` (`is_ipc_enabled=True`), child process mapped the 4096-byte buffer and wrote back a pattern the parent observed.
>
> *Wall time: 1.0 s*
>
> **Notes** — Worth calling out because the folder name suggests multi-GPU: this is *inter-process*, not inter-device. It runs fine with one GPU and is the mechanism behind sharing a loaded model's memory across worker processes.

<details>
<summary><b>Full README — ipcMemoryPool</b></summary>

#### ipcMemoryPool (Python)

##### Description

This sample demonstrates how to share GPU memory between Python
processes using CUDA Inter-Process Communication (IPC) and
`cuda.core`'s IPC-enabled memory pools.

By default each process has its own CUDA virtual address space and
cannot see allocations made by another process. With an IPC-enabled
`DeviceMemoryResource` the parent allocates once, and the child
process maps that same physical GPU memory into its own address space
so both read and write the same bytes. The sample performs a
round-trip test:

1. Parent creates an IPC-enabled `DeviceMemoryResource` and allocates
   a `Buffer`.
2. Parent fills the buffer with a known pattern.
3. Parent sends the `Buffer` to a child process through an
   `multiprocessing.Queue`. cuda.core's pickle reducers re-create the
   memory resource and map the buffer in the child.
4. Child verifies the parent's pattern, writes a new pattern, and
   signals completion.
5. Parent verifies the child's writes.

##### What You'll Learn

- Enabling IPC on a `DeviceMemoryResource` with `ipc_enabled=True`
- Sending `Buffer` objects across process boundaries via `mp.Queue`
- How cuda.core's pickle reducers rebuild the MR and map the buffer
  in the receiving process
- Why `multiprocessing` must use the `"spawn"` start method with CUDA
- Detecting IPC support at runtime (POSIX file-descriptor handle
  type, memory-pool support, Linux-only)

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - IPC-enabled memory resources and buffer reducers
- `cupy` - zero-copy views over the shared device memory via DLPack
- `multiprocessing` - standard library process management

##### Key APIs

###### From `cuda.core`

- `DeviceMemoryResource(device, options=DeviceMemoryResourceOptions(ipc_enabled=True))` - create an IPC-enabled memory pool
- `DeviceMemoryResourceOptions(max_size=..., ipc_enabled=True)` - configure the underlying pool
- `mr.allocate(nbytes)` - allocate a `Buffer` from the IPC pool
- `Buffer.is_mapped` - True when the buffer is usable in the current process
- `Device.properties.memory_pools_supported` - runtime feature check
- `Device.properties.handle_type_posix_file_descriptor_supported` - runtime feature check

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Device that supports CUDA memory pools and POSIX file-descriptor IPC handles (the sample detects and reports this at startup)
- Minimum GPU memory: 512 MB

###### Software

- Linux x86_64 (POSIX file-descriptor IPC handles are not available on Windows or macOS)
- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
python ipcMemoryPool.py
```

###### With custom parameters

```bash
# Larger shared buffer
python ipcMemoryPool.py --elements 65536

# Use a specific GPU
python ipcMemoryPool.py --device 1
```

On platforms or devices that do not support CUDA IPC, the sample
prints a diagnostic and exits cleanly with status 0.

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

Created IPC-enabled DeviceMemoryResource (is_ipc_enabled=True)
Parent wrote pattern (first 5 values): [100. 101. 102. 103. 104.]
Parent sent buffer to child pid=<pid>; waiting...
[child pid=<pid>] received buffer: is_mapped=True, size=4096
Parent sees child's pattern (first 5 values): [-0. -1. -2. -3. -4.]
IPC round-trip: OK
```

**Note:** Device name, compute capability, and child PID will vary
based on your system.

##### Files

- `ipcMemoryPool.py` - Python implementation using `cuda.core` IPC memory pools
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core` memory API](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html#memory)
- Upstream `cuda.core` IPC tests: [`test_memory_ipc.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/tests/memory_ipc/test_memory_ipc.py)
- [CUDA IPC programming guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#interprocess-communication)


</details>

<br>

### multiGPUGradientAverage

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/multiGPUGradientAverage
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> mpirun --oversubscribe -np 2 python multiGPUGradientAverage.py
> ```
>
> **Result** — Test PASSED with 2 ranks oversubscribed onto the single GPU. Kernel 32.571 ms, MPI Allreduce (host-staged) 4.590 ms, total 37.162 ms.
>
> **Notes** — **Gotcha:** running it bare gives `ERROR: This sample requires at least 2 MPI processes!`. You need a launcher — `mpi4py` alone is not enough. On this box `libopenmpi40` was present but `mpirun` was not; `sudo apt install openmpi-bin` supplied it. `--oversubscribe` lets both ranks share the one GPU, which is enough to exercise the gradient-averaging logic even though it proves nothing about scaling.

<details>
<summary><b>Full README — multiGPUGradientAverage</b></summary>

#### Sample: multiGPUGradientAverage (Python)

##### Description

This sample demonstrates gradient averaging across multiple GPUs using MPI and cuda.core. Each GPU computes local gradients, which are synchronized (averaged) across all GPUs using MPI Allreduce with host-staging (GPU → CPU → MPI → CPU → GPU) for maximum compatibility.

##### What you will learn

- How to initialize MPI for multi-process GPU communication
- How to map MPI ranks to CUDA devices consistently
- How to integrate cuda.core streams with CuPy using `Stream.from_external`
- How to compile and launch custom CUDA kernels using cuda.core
- How to use cuda.core Event for GPU timing measurements
- How to use MPI Allreduce with host-staging for universal compatibility

##### Prerequisites

- Python 3.10+
- CUDA Toolkit 13.0+
- Standard MPI implementation (OpenMPI, MPICH, or Intel MPI)
- Multiple NVIDIA GPUs (tested with 2+ GPUs)

##### Installation

```bash
pip install -r requirements.txt
```

##### Running

**IMPORTANT:** This sample **MUST** be launched by an MPI runtime with at
least 2 processes. On Linux/macOS this is typically `mpirun`; on Windows with
Microsoft MPI the launcher is `mpiexec` (and the flag for process count is
`-n`). Either form is accepted by most MPI stacks.

Linux / macOS (OpenMPI, MPICH, Intel MPI):

```bash
# Single node (2 GPUs)
mpirun -np 2 python multiGPUGradientAverage.py --size 10000

# Single node (4 GPUs)
mpirun -np 4 python multiGPUGradientAverage.py --size 10000

# With specific GPUs
CUDA_VISIBLE_DEVICES=0,2 mpirun -np 2 python multiGPUGradientAverage.py
```

Windows (Microsoft MPI — `mpiexec` is installed under
`C:\Program Files\Microsoft MPI\Bin\` and is not on PATH by default):

```powershell
& "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe" -n 2 `
    python multiGPUGradientAverage.py --size 10000
```

##### Sample Output

```
[Rank 0] World size = 4

======================================================================
Multi-GPU Gradient Average Demo
======================================================================
Number of MPI ranks (GPUs): 4
Gradient vector length per GPU: 10000
Device: NVIDIA GeForce RTX 4090
Computation: gradients computed on GPU via cuda.core.
Communication: gradients averaged via MPI_Allreduce on host (CPU) buffers.
======================================================================

Sample averaged gradient values (rank 0):
  avg_grad[0] = 1.500000
  avg_grad[5000] = 6.500000
  avg_grad[9999] = 11.499000

Expected values:
  expected[0] = 1.500000
  expected[5000] = 6.500000
  expected[9999] = 11.499000

Verifying gradient averaging correctness...
[PASS] Gradient averaging is correct.
[PASS] Gradient averaging is correct on all ranks.

Performance:
  Kernel time (GPU only): 0.123 ms
  MPI communication time (host-staging, end-to-end): 0.456 ms
  Total time: 0.579 ms

======================================================================
Demo complete.
======================================================================
```

##### Key Technical Details

The sample uses cuda.core streams and makes CuPy use them via `Stream.from_external`:

```python
stream = device.create_stream()
cp.cuda.Stream.from_external(stream).use()
```

GPU timing is measured using cuda.core Event:

```python
from cuda.core import EventOptions
timing_options = EventOptions(enable_timing=True)
start_event = stream.record(options=timing_options)
# ... GPU work ...
end_event = stream.record(options=timing_options)
end_event.sync()
kernel_time = end_event - start_event  # Returns milliseconds
```

The host-staging pattern transfers data GPU → CPU → MPI → CPU → GPU for universal MPI compatibility without requiring CUDA-aware MPI.

##### Troubleshooting

**Error: "This sample requires at least 2 MPI processes!"**

Solution:
- Linux / macOS: `mpirun -np 2 python multiGPUGradientAverage.py`
- Windows (Microsoft MPI): `& "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe" -n 2 python multiGPUGradientAverage.py`
  (or `mpiexec -n 2 ...` after adding `C:\Program Files\Microsoft MPI\Bin\` to `PATH`).

See the **Running** section above for fully-formed examples.


</details>

<br>

### simpleP2P

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/simpleP2P
> python simpleP2P.py
> ```
>
> **Result** — **Waived — correctly.** `CUDA-capable device count: 1` -> `Two or more GPUs with Peer-to-Peer access capability are required, waiving this sample.` Exit code 2.
>
> *Wall time: 0.2 s*
>
> **Notes** — This is the one sample that cannot demonstrate its point on this machine, and the only one not fully exercised. The graceful waive is the sample behaving as designed, not a failure. The C++ `p2pBandwidthLatencyTest` in `build/cpp/5_Domain_Specific/` has the same requirement.

<details>
<summary><b>Full README — simpleP2P</b></summary>

#### Sample: simpleP2P (Python)

##### Description

This sample demonstrates peer-to-peer (P2P) memory access between multiple GPUs in CUDA using the cuda.core Python library. P2P allows GPUs to directly access each other's memory without routing data through the host (CPU), enabling efficient multi-GPU applications. This sample detects P2P-capable GPUs, enables peer access, measures bandwidth using CUDA events for accurate GPU-side timing, and launches kernels (using grid-stride loops) that read from one GPU's memory and write to another GPU's memory.

##### What you will learn

- How to detect multiple CUDA-capable GPUs using `system.get_num_devices()` and `Device(id)`
- How to check P2P capability between GPU pairs using `device.can_access_peer()`
- How to enable and disable peer access using `DeviceMemoryResource.peer_accessible_by`
- How to allocate device memory on specific GPUs using `DeviceMemoryResource`
- How to perform direct GPU-to-GPU memory transfers with explicit event-based synchronization
- How to measure P2P bandwidth using CUDA events for accurate GPU-side timing
- How to use event-based synchronization between streams for sequential bandwidth measurement
- How to launch kernels on one GPU that access memory from another GPU
- How to compile and launch CUDA kernels using cuda.core's `Program` and `launch` APIs with grid-stride loops
- How to validate multi-GPU computation results
- How to properly clean up resources using try/finally blocks

##### Key libraries

- `numpy` - CPU array operations and data initialization
- `cuda-core` - Modern Python interface to CUDA runtime with full P2P support

##### Key APIs

**From cuda.core:**
- `system` – Pre-instantiated singleton for system-level CUDA information
- `system.get_num_devices()` – Get number of CUDA-capable devices
- `Device(id)` – Get specific CUDA device handle
- `device.can_access_peer(peer)` – Check if this device can access peer device memory
- `device.set_current()` – Set active device for subsequent operations
- `device.create_stream()` – Create CUDA stream for kernel execution
- `DeviceMemoryResource(device)` – Create memory resource for specific GPU
- `memory_resource.peer_accessible_by` – Get/set which devices can access this memory pool's allocations
  - Example: `mr.peer_accessible_by = [1]` grants device 1 access
  - Example: `mr.peer_accessible_by = []` revokes all access
- `PinnedMemoryResource()` – Allocate pinned (page-locked) host memory
- `EventOptions(enable_timing=True)` – Create options for CUDA events with timing enabled
- `stream.record(options=event_options)` – Record a CUDA event on a stream
- `event.elapsed_time(start_event)` – Get elapsed time in milliseconds between two events
- `stream.wait_event(event)` – Make a stream wait for an event to complete
- `stream.close()` – Clean up stream resources
- `Program()` – Compile CUDA C++ kernel code
- `LaunchConfig()` – Configure kernel launch parameters (grid, block)
- `launch()` – Launch compiled kernel with arguments
- `buffer.copy_from(src, stream=stream)` – Copy data from source buffer asynchronously
- `buffer.copy_to(dst, stream=stream)` – Copy data to destination buffer asynchronously

**From DLPack:**
- `numpy.from_dlpack()` – Create NumPy array view of memory buffer

**Memory Management:**
- Resources (streams, buffers) should be cleaned up using try/finally blocks to ensure proper cleanup even if errors occur
- Streams should be explicitly closed with `stream.close()` in finally blocks

##### Peer-to-Peer (P2P): When to Use

###### Benefits
- **Direct GPU-to-GPU transfers**: Bypass host memory for faster communication
- **Higher bandwidth**: PCIe or NVLink bandwidth between GPUs (up to 600 GB/s with NVLink)
- **Lower latency**: No CPU involvement in data transfers
- **Efficient multi-GPU**: Essential for scaling deep learning, HPC, and simulation workloads
- **Simplified programming**: Kernels can directly access remote GPU memory

###### Requirements
- **Two or more GPUs**: System must have multiple CUDA-capable GPUs
- **P2P support**: GPUs must be P2P-capable (check with `can_access_peer()`)
- **PCIe topology**: Usually requires GPUs on same PCIe root complex
- **Platform support**: Not available on Mac OSX, limited on ARM platforms

###### Best Use Cases
1. Multi-GPU deep learning training (model parallelism, data parallelism)
2. Large-scale scientific simulations across multiple GPUs
3. Real-time rendering with multiple GPUs
4. GPU clusters with direct GPU communication
5. Reducing CPU-GPU traffic in multi-GPU systems

##### Requirements

1. **Two or more NVIDIA Graphics Cards** with CUDA support and P2P capability
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit 13.0+** installed on your system
4. **Python 3.10 or newer**
5. **Proper PCIe topology** (GPUs should be on same PCIe root complex for best performance)

**Note**: This sample will gracefully exit if fewer than 2 GPUs are detected or if P2P is not supported between any GPU pair.

**Install packages:**
```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install numpy>=2.3.2 cuda-core>=1.0.0 cuda-python>=13.0.0
```

##### How to run

Basic usage:
```bash

# Run with default parameters (16M elements = 64MB)
python simpleP2P.py
```

With custom parameters:
```bash
# Use 32M elements (128MB)
python simpleP2P.py --num_elements 33554432

# Show help
python simpleP2P.py --help
```

###### Command line arguments

- `--num_elements`: Number of elements in arrays (default: 16777216)
  - Each array uses `num_elements * 4 bytes` (float32)
  - Default: 64 MB per array
  - Sample allocates 2 device buffers + 1 host buffer

##### Expected Output

```
======================================================================
simpleP2P - CUDA Python Sample
======================================================================

Starting...

Checking for multiple GPUs...
CUDA-capable device count: 2

Checking GPU(s) for support of peer to peer memory access...
> Peer access from Tesla T10 (GPU0) -> Tesla T10 (GPU1): Yes
> Peer access from Tesla T10 (GPU1) -> Tesla T10 (GPU0): Yes

Using GPU0 (Tesla T10) and GPU1 (Tesla T10)

Allocating buffers (64MB on GPU0, GPU1 and CPU Host)...
  Peer access enabled: GPU0 <-> GPU1
  Peer access status: MR0 accessible by (1,), MR1 accessible by (0,)
  Memory allocated successfully

Measuring P2P bandwidth...
  Performing 100 ping-pong copies between GPUs...
  P2P bandwidth: 12.37 GB/s

Preparing host buffer and memcpy to GPU0...
  Data initialized and copied to GPU

Compiling CUDA kernel...
  Kernels compiled successfully

Run kernel on GPU1, taking source data from GPU0 and writing to GPU1...
  Kernel execution complete

Run kernel on GPU0, taking source data from GPU1 and writing to GPU0...
  Kernel execution complete

Copy data back to host from GPU0 and verify results...

Checking results...
  Comparing 16,777,216 elements...
Test PASSED
  [PASS] Validation PASSED

Disabling peer access...
  Peer access revoked: MR0 accessible by (), MR1 accessible by ()

======================================================================
simpleP2P completed successfully!
======================================================================

Shutting down...
```

**Note**: P2P bandwidth varies based on:
- PCIe generation
- NVLink
- System topology and configuration

##### Files

- `simpleP2P.py` – Main Python implementation
- `README.md` – This file
- `requirements.txt` – Python package dependencies


</details>

---
