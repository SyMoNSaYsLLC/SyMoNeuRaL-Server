# 1_GettingStarted — Getting started

8 sample document(s), each with the verified *On this box* result and the complete upstream README.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

## 1_GettingStarted — Getting started

Eight samples covering device discovery, your first runtime-compiled kernel, host↔device transfer, unified memory and profiling. Work these in the order listed.

<br>

### deviceQuery

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
> python deviceQuery.py
> ```
>
> **Result** — PASS. Reports sm_120, 70 MPs, 15858 MB global, 256-bit bus, 48 MB L2, 2 copy engines, ECC disabled, cooperative launch supported.
>
> *Wall time: 0.6 s*
>
> **Notes** — The C++ twin is already built: `$CUDA_SAMPLES/build/cpp/1_Utilities/deviceQuery/deviceQuery`. Run both — the Python one uses `cuda.core`, the C++ one the runtime API, and they agree.

<details>
<summary><b>Full README — deviceQuery</b></summary>

#### Sample: Device Query (Python)

##### Description

Query and display detailed properties of all CUDA-capable devices in your system using the modern `cuda.core` API.

##### What You'll Learn

- How to enumerate CUDA devices in the system
- Using the `cuda.core` API for device management
- Querying comprehensive device properties (compute capability, memory, limits)
- Accessing low-level device attributes via `cuda.bindings`
- Checking peer-to-peer (P2P) access capabilities between GPUs

##### Key Libraries

- `cuda.core` - Modern CUDA Python API
- `cuda.bindings` - Low-level CUDA bindings for runtime and driver APIs

##### Key APIs

###### From `cuda.core`:

- `Device.get_all_devices()` - Get tuple of all available Device instances
- `Device(device_id)` - Get Device object for specific device ID
- `system.get_driver_version()` - Query CUDA driver version
- `Device.set_current()` - Set the current device for API calls
- `Device.properties` - Access comprehensive device properties
- `Device.name` - Get device name string
- `Device.can_access_peer()` - Check P2P access to peer device

###### From `cuda.bindings.runtime`:

- `cudart.cudaRuntimeGetVersion()` - Get CUDA runtime version
- `cudart.cudaDeviceGetAttribute()` - Query specific device attributes

###### From `cuda.bindings.driver`:

- `cuda.cuMemGetInfo()` - Get memory information for current device

##### Device Properties Queried

###### Compute Capabilities:
- Compute capability version (major.minor)
- Driver and runtime versions
- Number of multiprocessors and CUDA cores

###### Memory Information:
- Total global memory
- Memory clock rate and bus width
- L2 cache size
- Constant and shared memory sizes
- Maximum memory pitch

###### Execution Configuration Limits:
- Maximum threads per block and per multiprocessor
- Maximum block dimensions (x, y, z)
- Maximum grid dimensions (x, y, z)
- Warp size
- Registers per block

###### Texture Capabilities:
- Maximum texture dimensions (1D, 2D, 3D)
- Maximum layered texture sizes

###### Feature Support:
- Unified Addressing (UVA)
- Managed Memory
- Compute Preemption
- Cooperative Kernel Launch
- ECC support
- Host page-locked memory mapping
- Concurrent copy and kernel execution

###### System Information:
- PCI bus information
- Compute mode
- Driver mode (Windows only)
- P2P access matrix (multi-GPU systems)

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support (any compute capability)
- No specific GPU memory requirement (query only)

###### Software:

- CUDA Toolkit 13.0 or newer (recommended; matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` package (>=13.0.0)
- `cuda-core` package (>=1.0.0)

##### Installation

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
pip install -r requirements.txt
```

The requirements.txt installs:
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### How to Run

###### Basic usage:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
python deviceQuery.py
```

###### Skip P2P information:

```bash
python deviceQuery.py --no-p2p
```

##### Expected Output

```
[CUDA Device Query using CUDA Core API]
Detected 1 CUDA Capable device(s)

Device 0: <Your GPU Name>
  CUDA Driver Version / Runtime Version          12.4 / 12.6
  CUDA Capability Major/Minor version number:    8.9
  Total amount of global memory:                 24217 MBytes (25393954816 bytes)
  (132) Multiprocessors, (128) CUDA Cores/MP:    16896 CUDA Cores
  GPU Max Clock rate:                            1980 MHz (1.98 GHz)
  Memory Clock rate:                             10501 Mhz
  Memory Bus Width:                              384-bit
  L2 Cache Size:                                 67108864 bytes
  Maximum Texture Dimension Size (x,y,z)         1D=(131072), 2D=(131072, 65536), 3D=(16384, 16384, 16384)
  Maximum Layered 1D Texture Size, (num) layers  1D=(32768), 2048 layers
  Maximum Layered 2D Texture Size, (num) layers  2D=(32768, 32768), 2048 layers
  Total amount of constant memory:               65536 bytes
  Total amount of shared memory per block:       49152 bytes
  Total shared memory per multiprocessor:        102400 bytes
  Total number of registers available per block: 65536
  Warp size:                                     32
  Maximum number of threads per multiprocessor:  1536
  Maximum number of threads per block:           1024
  Max dimension size of a thread block (x,y,z):  (1024, 1024, 64)
  Max dimension size of a grid size    (x,y,z):  (2147483647, 65535, 65535)
  Maximum memory pitch:                          2147483647 bytes
  Texture alignment:                             512 bytes
  Concurrent copy and kernel execution:          Yes with 2 copy engine(s)
  Run time limit on kernels:                     Yes
  Integrated GPU sharing Host Memory:            No
  Support host page-locked memory mapping:       Yes
  Device has ECC support:                        Enabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:
     < Default (multiple host threads can use cudaSetDevice() with device simultaneously) >

Done
```

**Note:** Output will vary based on your specific GPU model and system configuration.

For multi-GPU systems, the output will include information for all detected devices and a P2P access matrix showing which GPUs can directly access each other's memory.

##### Files

- `deviceQuery.py` - Python implementation using cuda.core API
- `requirements.txt` - Sample dependencies

##### Use Cases

- **System Diagnostics** - Verify CUDA installation and GPU detection
- **Hardware Profiling** - Understand GPU capabilities before optimization
- **Multi-GPU Systems** - Identify P2P topology for optimal data placement
- **Kernel Development** - Determine execution configuration limits
- **Compatibility Checks** - Verify compute capability requirements

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API Guide](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CUDA Programming Guide - Device Information](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#device-enumeration)


</details>

<br>

### systemInfo

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
> python systemInfo.py
> ```
>
> **Result** — PASS. Driver 13.3 user-mode / 610.57.4 kernel-mode, NVML (13,610,57,4), branch r610_85, BLACKWELL, 15.92 GiB.
>
> *Wall time: 0.2 s*
>
> **Notes** — Fastest sanity check that the driver stack is alive. `5070ti.txt` in this folder is a saved run from this very box.

<details>
<summary><b>Full README — systemInfo</b></summary>

#### Sample: System Information Query (Python)

##### Description

This sample demonstrates how to inspect the CUDA driver, NVML, and every
installed GPU through the
[`cuda.core.system`](https://nvidia.github.io/cuda-python/cuda-core/latest/)
module.

`cuda.core.system` wraps the NVIDIA Management Library (NVML) and can be
imported without CUDA being installed or initialized, so it is useful as a
lightweight pre-flight check before any CUDA context is created. The script
prints driver and NVML versions, the current process name, per-device
metadata (name, compute capability, architecture, memory, PCI info,
temperature, performance state), and, on multi-GPU systems, the topology
and peer-to-peer capabilities between each pair of devices.

##### What You'll Learn

- Querying CUDA driver and NVML versions with `cuda.core.system`
- Enumerating GPUs without creating a CUDA context
- Reading per-device metadata exposed by NVML (name, UUID, memory usage,
  temperature, performance state)
- Inspecting GPU-to-GPU topology and peer-to-peer (P2P) capabilities

##### Key Libraries

- [`cuda.core.system`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - Python wrapper around NVML

##### Key APIs

From `cuda.core.system`:

- `get_driver_version()`, `get_driver_version_full()`, `get_driver_branch()` - CUDA driver version tuple and branch string
- `get_nvml_version()` - NVML library version
- `get_num_devices()` - number of GPUs visible to NVML
- `get_process_name(pid)` - process name for a given PID
- `Device(index=...)` - NVML-backed device handle (no CUDA context required)
  - `name`, `uuid`, `cuda_compute_capability`, `arch`, `brand`
  - `memory_info` (`total`, `used`, `free`)
  - `pci_info` (`domain`, `bus`, `device`, `bus_id`)
  - `temperature.sensor(TemperatureSensors.TEMPERATURE_GPU)`
  - `performance_state`
- `get_topology_common_ancestor(dev0, dev1)` - `GpuTopologyLevel` between two devices
- `get_p2p_status(dev0, dev1, GpuP2PCapsIndex.P2P_CAPS_INDEX_READ)` - peer-access capability between two devices

Import stable symbols from the top-level `cuda.core` package (not `cuda.core.experimental`).

##### Requirements

1. **NVIDIA Graphics Card** with CUDA support
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit** installed on your system
4. **Python 3.12 or newer**

###### Hardware

- One or more NVIDIA GPUs
- Driver compatible with `cuda-python` 13.x

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
python systemInfo.py
```

###### Skip topology queries

Useful on machines with only one GPU or to shorten the output:

```bash
python systemInfo.py --no-topology
```

##### Expected Output

Output varies with your hardware. On a machine with two GPUs you should see
something like:

```
======================================================================
Driver / NVML
======================================================================
CUDA driver version: 13.2
CUDA driver version (full): (13, 2, 0)
NVML version: (13, 595, 58, 3)
Driver branch: r595_88
Current process: /usr/bin/python

======================================================================
Devices detected: 2
======================================================================

-- Device 0 --
Name: <Your GPU Name>
UUID: ...
Compute capability: 8.9
Architecture: ADA
Brand: BRAND_GEFORCE
Memory: total=23.99 GiB, used=960.00 KiB, free=23.52 GiB
PCI: domain=0000 bus=41 device=00 id=00000000:41:00.0
Temperature (GPU sensor): 47 C
Performance state: <Pstates.PSTATE_8: 8>

...

======================================================================
GPU topology and peer-to-peer
======================================================================
Device 0 <-> Device 1: topology=TOPOLOGY_HOSTBRIDGE, p2p_read=..., p2p_write=...

Done
```

**Note:** Device names, compute capability, temperatures, and topology
details will vary based on your GPUs and system.

##### Files

- `systemInfo.py` - Python implementation using `cuda.core.system`
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core.system` API reference](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html)
- [NVML reference](https://docs.nvidia.com/deploy/nvml-api/)


</details>

<br>

### vectorAdd

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
> python vectorAdd.py
> ```
>
> **Result** — Test PASSED. Compiled `vectorAdd<float>` for sm_120 at runtime, 196 blocks x 256 threads over 50000 elements.
>
> *Wall time: 3.6 s*
>
> **Notes** — First run costs ~3.6 s almost entirely in NVRTC compilation, not in the kernel. That compile cost is why `cudaGraphs` and `jitLtoLinking` exist.

<details>
<summary><b>Full README — vectorAdd</b></summary>

#### Sample: Vector Addition (Python)

##### Description

Run your first GPU kernel: add two vectors element-wise on the GPU using the [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) API with runtime compilation.

##### What You'll Learn

- Writing CUDA kernels in C++ with template support
- Runtime compilation of CUDA kernels from Python
- Using `cuda.core` for device management, programs, and launches
- Configuring and launching kernels with grid and block dimensions
- Using CuPy for GPU memory management
- Verifying GPU results against CPU computation

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) — Pythonic access to CUDA runtime and compilation
- `cupy` — GPU array library for Python

##### Key APIs

###### From `cuda.core`

- `Device` — Initialize and manage CUDA device
- `Program` — Create program from kernel source code
- `ProgramOptions` — Set compilation options (C++ standard, architecture)
- `LaunchConfig` — Configure kernel launch parameters
- `launch` — Execute kernel on specified stream

Import stable symbols from the top-level package (not `cuda.core.experimental`). See the [cuda.core documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/).

###### From CuPy

- `cp.random.rand()` — Generate random arrays on GPU
- `cp.empty()` — Allocate uninitialized GPU arrays
- `cp.allclose()` — Verify results with tolerance

###### From `cuda_samples_utils`

- `verify_array_result()` — Verify computation results

##### Kernel Techniques

- **1D Grid-Stride Loop** — Handle arbitrary array sizes with fixed grid
- **Template Programming** — Generic kernel for different data types
- **Bounds Checking** — Prevent out-of-bounds memory access

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
pip install -r requirements.txt
```

The requirements.txt installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
python vectorAdd.py
```

###### With custom parameters

```bash
# Custom vector size
python vectorAdd.py --elements 1000000

# Use specific GPU
python vectorAdd.py --device 1

# Skip verification for benchmarking
python vectorAdd.py --no-verify
```

##### Expected Output

```
[Vector addition using CUDA Core API]
Device: <Your GPU Name>
Compute Capability: sm_<XX>
Compiling kernel 'vectorAdd<float>'...
Kernel compiled successfully
[Vector addition of 50000 elements]
CUDA kernel launch with 196 blocks of 256 threads
Verifying result...
Test PASSED

Done
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `vectorAdd.py` — Python implementation using cuda.core API
- `README.md` — This file
- `requirements.txt` — Sample dependencies
- `../../Utilities/cuda_samples_utils.py` — Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### numpyVsCupy

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/numpyVsCupy
> python numpyVsCupy.py
> ```
>
> **Result** — PASS. 4096x4096 dot: NumPy 0.518 s vs CuPy 0.0189 s = **27x**. Host->device transfer of the two arrays cost 0.090 s.
>
> *Wall time: 1.9 s*
>
> **Notes** — Note the transfer line: 0.090 s to move the inputs, 0.019 s to do the maths. On this box the PCIe Gen 3 x8 link (see Appendix A) makes transfer 4.8x more expensive than the compute. Keep data resident on the GPU.

<details>
<summary><b>Full README — numpyVsCupy</b></summary>

#### Sample: Numpy vs. Cupy (Python)

##### Description

This sample demonstrates performance comparison between NumPy (CPU) and CuPy (GPU) for matrix multiplication operations. It benchmarks the execution time of matrix dot products on both CPU and GPU, showing the performance benefits of GPU acceleration for numerical computations.

##### What you will learn

- How to set up and use CuPy for GPU-accelerated numerical computations.
- How to benchmark NumPy vs CuPy performance for matrix operations.
- How to transfer data between CPU (NumPy) and GPU (CuPy) memory using `cp.asarray()`.
- How to use CUDA device management with the cuda-core library.
- How to validate computational results between CPU and GPU implementations using `np.testing.assert_allclose()`.
- How to handle GPU warmup to avoid first-run overhead in benchmarking.
- How to create and manage explicit CUDA streams with `device.create_stream()`.
- How to properly cleanup streams with `stream.close()` in try/finally blocks.
- How to access GPU device information (name, compute capability).
- How to create timing context managers for performance measurement using CUDA events.

##### Key libraries

- `numpy`
- `cupy`
- `cuda-core`

##### Key APIs

**From cuda.core:**
- `Device()` – Get CUDA device object for specific GPU
- `device.create_stream()` – Create explicit CUDA stream
- `stream.close()` – Close and cleanup stream resources

##### Requirements
1. **NVIDIA Graphics Card** with CUDA support
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit** installed on your system
4. **Python 3.12 or newer**

**Install packages:**
```bash
pip install -r requirements.txt
```

##### How to run

Basic usage:
```bash
# Pre-steps:
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
# Run from the Python directory:
cd $CUDA_SAMPLES/python/1_GettingStarted/numpyVsCupy
python -m 1_GettingStarted.numpyVsCupy.numpyVsCupy
```

With custom parameters:
```bash
python -m 1_GettingStarted.numpyVsCupy.numpyVsCupy --n_size 5000
```

###### Command line arguments

- `--n_size`, `-n`: Size of the matrix (n * n) for benchmarking (default: 4096)

##### Expected Output
```
Validation PASSED: NumPy and CuPy results match within tolerance
Demo completed successfully!
```

##### Files
- `numpyVsCupy.py` – Python implementation
- `README.md` – This file
- `requirements.txt` – Required packages


</details>

<br>

### simplePrint

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/simplePrint
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python simplePrint.py
> ```
>
> **Result** — PASS. Both the `cuda.core` kernel and the Numba `cuda.grid(3)` kernel printed their block/thread IDs.
>
> *Wall time: 0.9 s*
>
> **Notes** — **Never install `numba-cuda` into the base venv.** It pins `numpy<2.5` and will silently downgrade a clean 2.5.2 install to 2.4.6. Run it from `$VENVS/venv-extras` instead, where the downgrade is contained and harmless.

<details>
<summary><b>Full README — simplePrint</b></summary>

#### simplePrint - Printing from CUDA Kernels

##### Description

This sample demonstrates how to use `printf()` inside CUDA kernels using **two different approaches**:

1. **CUDA C++ kernels** compiled with `cuda.core.Program` - Full C++ features and control
2. **Numba CUDA kernels** - Pythonic kernel authoring using `numba.cuda.grid()` for modern indexing

The sample shows basic device management, kernel compilation with inline CUDA C++ code, and multi-dimensional kernel launches (2D grid × 3D blocks) using modern CUDA Python. The Numba example demonstrates the recommended `numba.cuda.grid()` indexing style while also showing how it relates to classic CUDA C++ block/thread IDs. Both approaches use `cuda.core` APIs for stream management and synchronization, demonstrating interoperability.

This is the Python equivalent of the C++ `simplePrintf` sample, enhanced with Numba CUDA examples.

##### Key Concepts

CUDA Python (cuda.core), Numba CUDA, Kernel Compilation, Printf in Kernels, Multi-dimensional Launch, Pythonic GPU Programming, Modern Thread Indexing (grid()), Stream-based Execution, cuda.core/Numba Interoperability

##### CUDA APIs involved

###### [cuda.core (cuda-python)](https://nvidia.github.io/cuda-python/)

- `Device()` - Device management
- `Device.create_stream()` - Create CUDA streams
- `Stream.sync()` - Synchronize stream execution
- `Program()` - Compile CUDA C++ kernels
- `LaunchConfig()` - Configure kernel launch
- `launch()` - Execute kernels on streams

###### [Numba CUDA](https://nvidia.github.io/numba-cuda/)

- `@cuda.jit` - JIT compile Python functions to CUDA kernels
- `cuda.grid()` - Get global thread position (recommended modern approach)
- `cuda.blockIdx`, `cuda.threadIdx` - Thread/block indices (classic style)
- `cuda.gridDim`, `cuda.blockDim` - Grid/block dimensions
- **Note:** Uses `cuda.core` APIs for stream management (interoperability)

###### CUDA Kernel Functions

- `printf()` - Print from device code (C++)
- `print()` - Print from device code (Numba, limited formatting)
- `blockIdx`, `threadIdx` - Thread/block indices
- `gridDim`, `blockDim` - Grid/block dimensions

###### What You Learn

- Device initialization with `cuda.core.Device`
- Compiling CUDA C++ kernels with `Program` and `ProgramOptions`
- Writing Pythonic CUDA kernels with Numba's `@cuda.jit` decorator
- Using `numba.cuda.grid()` for modern thread indexing (recommended approach)
- Understanding the relationship between global coordinates and classic block/thread IDs
- **Interoperability**: Using `cuda.core` streams with Numba CUDA kernels
- Comparing CUDA C++ vs Pythonic kernel authoring approaches
- Multi-dimensional kernel launches (2D grid, 3D blocks)
- Using streams for kernel execution and synchronization
- Using `printf()` and `print()` in GPU kernels for debugging
- Understanding print limitations in Numba CUDA (no f-strings)
- Proper error handling and resource management

##### Requirements

###### Hardware:

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- `cuda-python` package (13.0+)
- `cuda-core` package (>=1.0.0)
- `numba-cuda` package (0.24.0+, for Pythonic kernel authoring)

Download and install:
- [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)
- [cuda-python package](https://nvidia.github.io/cuda-python/): `pip install cuda-python`
- [numba-cuda](https://nvidia.github.io/numba-cuda/): `pip install numba-cuda`

##### Build and Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run the sample
python simplePrint.py
```

##### Expected Output

```
Simple Print - Printing from CUDA Kernels
Demonstrating both CUDA C++ and Numba CUDA approaches

Device: <Your GPU Name>
Compute Capability: sm_<XX>

======================================================================
METHOD 1: CUDA C++ Kernel (via cuda.core.Program)
======================================================================
Advantage: Full C++ features, better for complex kernels

Compiling CUDA C++ kernel...
Kernel compiled successfully.

Kernel configuration:
  Grid:  (2, 2)
  Block: (2, 2, 2)
  Total threads: 32

Launching kernel with value=10. Output:

[0, 0]:		Value is: 10
[0, 1]:		Value is: 10
[0, 2]:		Value is: 10
[0, 3]:		Value is: 10
[0, 4]:		Value is: 10
[0, 5]:		Value is: 10
[0, 6]:		Value is: 10
[0, 7]:		Value is: 10
[1, 0]:		Value is: 10
...
[3, 7]:		Value is: 10

CUDA C++ kernel execution complete.


======================================================================
METHOD 2: Numba CUDA Kernel (Pythonic / modern indexing)
======================================================================
Advantage: Uses numba.cuda.grid(3) for global indexing,
           while still showing classic CUDA C++ IDs for reference.
           Uses cuda.core for stream management (interoperability).

Kernel configuration:
  Grid:  (2, 2)
  Block: (2, 2, 2)
  Total threads: 32

Launching Numba CUDA kernel (grid(3) + classic IDs) with value=10:
Uses numba.cuda.grid(3) to get global (x, y, z),
and prints the corresponding blockId/threadId like the C++ sample.
Stream managed by cuda.core for consistency with C++ example.

global[ 0 , 0 , 0 ]  -> [ 0 ,  0 ]: Value is: 10
global[ 1 , 0 , 0 ]  -> [ 0 ,  1 ]: Value is: 10
global[ 0 , 1 , 0 ]  -> [ 0 ,  2 ]: Value is: 10
...
global[ 3 , 3 , 1 ]  -> [ 3 ,  7 ]: Value is: 10

Numba CUDA kernel execution complete.

======================================================================
Done! Both kernel approaches demonstrated successfully.
======================================================================
```

##### Understanding the Output

- **Grid**: 2×2 = 4 blocks (labeled 0-3)
- **Block**: 2×2×2 = 8 threads per block (labeled 0-7)
- **Total**: 32 threads, each printing its position and value

###### CUDA C++ Kernel:
Each thread calculates:
- Block ID (linear): `blockIdx.y * gridDim.x + blockIdx.x`
- Thread ID (linear): `threadIdx.z * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x`

###### Numba CUDA Kernel:
Each thread shows:
- **Global position** using `numba.cuda.grid(3)` → `(x, y, z)` coordinates across entire grid
- **Classic IDs** (block ID, thread ID) calculated the same way as C++ for comparison
- This demonstrates how modern indexing relates to traditional CUDA C++ style

###### Comparing the Two Approaches

**CUDA C++ Kernel (Method 1):**
- Uses C++ syntax and `printf()` with full formatting control
- Requires compilation via `cuda.core.Program`
- Best for complex kernels needing C++ features (templates, libraries, etc.)
- Uses classic block/thread ID indexing
- Output: `[0, 0]:		Value is: 10` (clean formatting)

**Numba CUDA Kernel (Method 2):**
- Uses Python syntax with `@cuda.jit` decorator
- JIT compiled automatically when called
- Best for prototyping and simpler kernels
- **Modern indexing**: Uses `numba.cuda.grid(3)` to get global thread coordinates (recommended)
- Also shows classic block/thread IDs to help relate the two indexing models
- **Interoperability**: Uses `cuda.core` streams via `stream` for consistency
- Demonstrates that numba-cuda kernels can work seamlessly with cuda.core infrastructure
- Limited print formatting (no f-strings, basic `print()` only; adds spaces between arguments)
- Output: `global[ 0 , 0 , 0 ] -> [ 0 , 0 ]: Value is: 10` (shows both indexing styles; note extra spaces due to `print()` behavior)

##### Experiments

Try modifying:

###### For Both Approaches:
- **Grid size**: Change `grid=(4, 4)` for 16 blocks
- **Block size**: Change `block=(4, 4, 4)` for 64 threads per block
- **Conditional printing**: Print only from specific threads (e.g., `if threadId == 0:`)

###### CUDA C++ Specific:
- **Format strings**: Experiment with different `printf()` formats
- **Kernel code**: Add complex C++ computations before printing
- **External libraries**: Include CUDA math libraries or device functions (e.g., `<cuda/std/cmath>`, `<cub/cub.cuh>`)

###### Numba CUDA Specific:
- **Grid indexing**: Try `numba.cuda.grid(1)` or `numba.cuda.grid(2)` for different dimensions
- **Conditional printing**: Print only from threads where `x == 0` or `y == z`
- **Python operations**: Use NumPy-like operations in the kernel
- **Device math libraries**: Use [nvmath-python device APIs](https://docs.nvidia.com/cuda/nvmath-python/latest/device-apis/index.html) for optimized math operations (similar to CUDA math libraries in C++)
- **Shared memory**: Add `numba.cuda.shared.array()` for fast inter-thread communication
- **Atomic operations**: Try `numba.cuda.atomic.add()` for thread-safe updates
- **Print variations**: Experiment with what numba-cuda's `print()` can and cannot handle
- **Streams**: Create multiple `cuda.core` streams and launch numba-cuda kernels on them concurrently
- **Interoperability**: Mix numba-cuda kernels and CUDA C++ kernels on the same stream

##### Notes

###### General:
- Printing from GPU is relatively slow - use sparingly in production code
- Printf output is buffered and limited (~1MB buffer on most GPUs)

###### CUDA C++ Kernels:
- Always call `stream.sync()` after kernel launch to flush printf output
- Full `printf()` format string support (%, flags, width, precision)

###### Numba CUDA Kernels:
- **Recommended**: Use `numba.cuda.grid(ndim)` for thread indexing (modern, Pythonic)
  - `grid(1)` for 1D indexing, `grid(2)` for 2D, `grid(3)` for 3D
  - Returns global thread position across the entire grid
- **Interoperability**: Use `cuda.core` streams with Numba kernels via `stream`
  - Create streams: `stream = device.create_stream()`
  - Launch kernels: `kernel[grid, block, stream](args)`
  - Synchronize: `stream.sync()`
- Numba's `print()` has limited capabilities compared to Python's `print()`
- F-strings are NOT supported in Numba CUDA kernels
- Use comma-separated arguments: `print("Value:", x)` instead of f-strings
- **Note**: `print()` automatically adds spaces between comma-separated arguments (e.g., `print("[", x, "]")` outputs `[ 0 ]` not `[0]`)
- Always synchronize the stream to flush output

##### Files

- `simplePrint.py` - Python implementation using cuda.core API
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

###### CUDA Python (cuda.core):
- [cuda.core Documentation](https://nvidia.github.io/cuda-python/)
- [CUDA Python Examples](https://github.com/NVIDIA/cuda-python/tree/main/cuda_core/examples)

###### Numba CUDA:
- [Numba CUDA Documentation](https://nvidia.github.io/numba-cuda/)
- [numba.cuda.grid() Reference](https://nvidia.github.io/numba-cuda/reference/kernel.html#numba.cuda.grid)
- [nvmath-python Device APIs](https://docs.nvidia.com/cuda/nvmath-python/latest/device-apis/index.html) - Optimized math operations for Numba CUDA kernels

###### CUDA References:
- [CUDA C Programming Guide - Printf](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#formatted-output)
- [C++ simplePrintf Sample](https://github.com/NVIDIA/cuda-samples/tree/master/Samples/0_Introduction/simplePrintf)


</details>

<br>

### copyImageArraytoGPU

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
> python copyImageArraytoGPU.py
> ```
>
> **Result** — Test PASSED. 256x256x3 image round-tripped; mean pixel 127.33 computed on the GPU.
>
> *Wall time: 3.3 s*
>
> **Notes** — Shows the CuPy view over a `cuda.core` allocation — zero-copy interop between the two libraries, no extra transfer.

<details>
<summary><b>Full README — copyImageArraytoGPU</b></summary>

#### Sample: Image Array Copy to GPU (Python)

##### Description

Copy image arrays between CPU and GPU memory using the modern `cuda.core` API with optimal performance through pinned memory and asynchronous transfers.

##### What You'll Learn

- How to use pinned memory for faster CPU↔GPU transfers
- Using the `cuda.core` API for memory management
- Working with DLPack for zero-copy array views
- Performing asynchronous memory transfers with CUDA streams
- Interoperability between CUDA Core API and CuPy
- Proper CUDA resource management and cleanup

##### Key Libraries

- `cuda.core` - Modern CUDA Python API
- `numpy` - Array operations and DLPack support
- `cupy` - GPU array operations and CUDA interoperability

##### Key APIs

###### From `cuda.core`:

- `Device()` - Initialize and access CUDA device
- `Device.set_current()` - Set the current device for API calls
- `Device.create_stream()` - Create CUDA stream for async operations
- `Device.memory_resource` - Access device memory allocator
- `PinnedMemoryResource()` - Allocate pinned host memory
- `buffer.copy_to()` - Copy data between memory spaces
- `buffer.close()` - Release allocated memory

###### From `numpy`:

- `np.from_dlpack()` - Create array view from DLPack capsule
- `np.copyto()` - Copy data between arrays

###### From `cupy`:

- `cp.from_dlpack()` - Create GPU array view from DLPack capsule
- `cp.cuda.Stream.from_external()` - Use external CUDA stream

###### From `cuda_samples_utils`:

- `verify_array_result()` - Verify computation results

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support
- Sufficient GPU memory for image data (sample uses ~200KB for 256×256×3 image)

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- NumPy 2.3.2 or newer (required for DLPack support)
- `cuda-python` package (>=13.0.0+)
- `cuda-core` package (>=1.0.0)
- `cupy-cuda13x` package (14.0.0+)

##### Installation

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
pip install -r requirements.txt
```

The requirements.txt installs:
- `numpy` (2.3.2+, required for DLPack)
- `cuda-python` (>=13.0.0+)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (14.0.0+)

##### How to Run

###### Basic usage:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
python copyImageArraytoGPU.py
```

##### Expected Output

```
[Image Array Copy to GPU using CUDA Core API]
Device: NVIDIA GeForce RTX 4090
[Image array copy of 256x256x3 image]
Creating sample image...
Copying image to GPU...
Creating CuPy view of GPU data...
Mean pixel value (computed on GPU): 127.50
Copying image back from GPU...
Verifying result...
Test PASSED

Done
```

**Note:** Device name will vary based on your GPU.

##### Files

- `copyImageArraytoGPU.py` - Python implementation using cuda.core API
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API Guide](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [DLPack Specification](https://dmlc.github.io/dlpack/latest/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### blurImageUnifiedMemory

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/blurImageUnifiedMemory
> python blurImageUnifiedMemory.py
> ```
>
> **Result** — Test PASSED. Compiled for sm_120, blurred 256x256 grayscale, max difference from original 0.5076. Wrote `original_image.png` and `blurred_image.png` into the sample folder.
>
> *Wall time: 0.5 s*
>
> **Notes** — Writes two PNGs next to the script. Unified memory hides the copy, but on a discrete GPU behind Gen 3 x8 the copy still happens — it is convenience, not free bandwidth.

<details>
<summary><b>Full README — blurImageUnifiedMemory</b></summary>

#### Sample: Image Blur with Unified Memory (Python)

##### Description

Blur images on GPU using modern `cuda.core` APIs for kernel compilation, execution, and memory management. This sample demonstrates **zero-copy data sharing** between CPU and GPU using unified (managed) memory.

##### What You'll Learn

- Compiling CUDA kernels at runtime with `cuda.core.Program`
- Launching kernels with `cuda.core.launch` and `LaunchConfig`
- Using unified memory with `cuda.core.ManagedMemoryResource`
- **Zero-copy CPU access** to unified memory via `np.from_dlpack()`
- Seamless CPU/GPU memory access without explicit transfers

##### Key Concepts

###### Kernel Compilation with cuda.core.Program

```python
# Compile CUDA C++ kernel at runtime
program = Program(KERNEL_CODE, code_type="c++", options=options)
compiled = program.compile(target_type="cubin")
kernel = compiled.get_kernel("box_blur_3x3")
```

###### Kernel Launch with cuda.core.launch

```python
# Configure and launch kernel
config = LaunchConfig(grid=grid_size, block=block_size)

# Buffers can be passed directly as kernel arguments
launch(stream, config, kernel, src_buf, dst_buf, H, W)
```

###### Unified Memory (Managed Memory)

This sample uses `ManagedMemoryResource` for simplicity: a single allocation is accessible from both CPU and GPU without explicit transfers. For performance-critical workloads, consider `LegacyPinnedMemoryResource` + `DeviceMemoryResource` instead, which gives explicit control over host/device placement and transfer costs.

Unified memory is accessible from both CPU and GPU without explicit data transfers:

```python
# Allocate unified memory
options = ManagedMemoryResourceOptions(preferred_location=device.device_id)
mr = ManagedMemoryResource(options)
src_buf = mr.allocate(n_bytes, stream)
dst_buf = mr.allocate(n_bytes, stream)
try:
    # Synchronize to ensure allocations are complete before CPU access
    stream.sync()

    # Create numpy views of unified memory using DLPack protocol (zero-copy)
    src_np = np.from_dlpack(src_buf).view(np.float32).reshape(H, W)
    dst_np = np.from_dlpack(dst_buf).view(np.float32).reshape(H, W)

    # CPU writes directly to unified memory
    src_np[:] = input_data

    # Launch kernel - buffers can be passed directly as arguments
    launch(stream, config, kernel, src_buf, dst_buf, H, W)
    stream.sync()

    # Return zero-copy view; caller must close buffers when done
    return dst_np, src_buf, dst_buf
except Exception:
    src_buf.close()
    dst_buf.close()
    raise
```

When returning a zero-copy view, the caller must close the buffers after use (e.g., in a `try/finally` block) to avoid leaking managed memory.

##### Key APIs

###### From `cuda.core`:

- `Device` - CUDA device management
- `Program` - Runtime kernel compilation (NVRTC)
- `ProgramOptions` - Compilation options (architecture target)
- `LaunchConfig` - Kernel launch configuration (grid/block dimensions)
- `launch` - Execute compiled kernel
- `ManagedMemoryResource` - Unified memory allocation

###### Zero-Copy Techniques:

- `np.from_dlpack(buffer)` - Create numpy view of unified memory using DLPack protocol
- Pass `buffer` directly to `launch()` as kernel arguments
- When returning a zero-copy view, return `(view, src_buf, dst_buf)` and have the caller close buffers in `try/finally` after use

##### Kernel Techniques

- **2D Thread Mapping** - Each thread computes one output pixel
- **Stencil Pattern** - Read neighboring pixels (3x3 neighborhood)
- **Boundary Handling** - Clamp to edge for border pixels
- **Box Filter** - 3x3 averaging for blur effect

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support
- Minimum GPU memory: 256 MB

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- `cuda-python` package (13.0.0+)
- `cuda-core` package (>=1.0.0)
- `numpy` package (>=2.3.2)
- `pillow` package (10.0.0+)

###### Platform Support:

This sample relies on `ManagedMemoryResource` with **concurrent host access**
to managed allocations while GPU kernels are in flight. That behavior
requires the device property `concurrent_managed_access=True`, which is only
supported on Linux with HMM (Pascal and newer). On Windows (WDDM/MCDM/TCC)
the property is `False`, so the sample exits early with a waive message and
exit code `2` instead of attempting a run that would crash the process.

##### Installation

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/blurImageUnifiedMemory
pip install -r requirements.txt
```

##### How to Run

```bash
python blurImageUnifiedMemory.py
```

##### Expected Output

```
============================================================
Image Blur with Unified Memory (cuda.core)
============================================================

Device: <Your GPU Name>
Compute Capability: sm_<XY>

Compiling CUDA kernel with cuda.core.Program...
  Compiled for architecture: sm_<XY>

Image size: 256x256 grayscale
Creating sample image...
Blurring image on GPU...

Saving results...
  Saved: original_image.png
  Saved: blurred_image.png

Verifying result...
  Test PASSED
  Max difference from original: <value>
```

##### Output Files

- `original_image.png` - Test pattern image before blur
- `blurred_image.png` - Image after 3x3 box blur

##### Files

- `blurImageUnifiedMemory.py` - Python implementation using cuda.core
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [cuda.core.Program](https://nvidia.github.io/cuda-python/cuda-core/latest/generated/cuda.core.Program.html)
- [cuda.core.ManagedMemoryResource](https://nvidia.github.io/cuda-python/cuda-core/latest/generated/cuda.core.ManagedMemoryResource.html)
- [CUDA Managed Memory](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#um-unified-memory-programming-hd)


</details>

<br>

### kernelNsysProfile

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/kernelNsysProfile
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python kernelNsysProfile.py
> ```
>
> **Result** — PASSED. Vector Add, SAXPY and Transform kernels all verified against NumPy references, with NVTX ranges around each phase.
>
> *Wall time: 1.4 s*
>
> **Notes** — `nsys` is present at `/usr/local/cuda/bin/nsys` on this box. Profile with:
```bash
nsys profile -o /tmp/kprof --force-overwrite true python kernelNsysProfile.py
nsys stats /tmp/kprof.nsys-rep
```

<details>
<summary><b>Full README — kernelNsysProfile</b></summary>

#### Sample: Kernel Nsys Profiling - CUDA C++ Kernel Profiling with cuda.core (Python)

##### Description

This sample demonstrates how to profile custom CUDA C++ kernels compiled and launched with `cuda.core` using NVIDIA Nsight Systems. It implements three GPU operations (vector addition, SAXPY, vector transform) as custom kernels and shows how to instrument code with NVTX markers for profiling analysis.

##### What you will learn

- How to write and compile CUDA C++ kernels with `cuda.core.Program`
- How to launch kernels with `LaunchConfig` and manage CUDA streams
- How to use NVTX markers (`nvtx.annotate()`) to annotate code sections
- How to profile kernels with Nsight Systems and analyze performance
- Modern CUDA Python workflow with `cuda.core.Device` and proper resource cleanup

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- Packages: `numpy`, `cuda-python`, `cuda-core`, `cupy-cuda13x`, `nvtx` (see `requirements.txt`; NumPy >=2.3.2)

**Install:**
```bash
pip install -r requirements.txt
```

##### How to run

```bash
python kernelNsysProfile.py
python kernelNsysProfile.py --array-size 10000000  # Custom size
```

##### Nsys Profiling

**Basic profile:**
```bash
nsys profile -o gpu_profile python kernelNsysProfile.py
nsys-ui gpu_profile.nsys-rep  # View results
```

The program uses color-coded NVTX markers:
- **Purple**: Phase 2 (cuda.core Custom Kernels - main focus)
- **Yellow/Blue/Green**: Other phases
- **Cyan**: Nested operations

Focus on Phase 2 to analyze kernel execution times, launch overhead, and GPU utilization.

**For detailed Nsys usage and analysis techniques, see the [NVIDIA Nsight Systems documentation](https://docs.nvidia.com/nsight-systems/).**

##### Troubleshooting

**Missing packages:**
```bash
pip install -r requirements.txt
```

**Out of memory:**
```bash
python kernelNsysProfile.py -n 10000000  # Reduce array size
```

**Nsys not found:**
```bash
export PATH=/usr/local/cuda/bin:$PATH
```

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [NVIDIA Nsight Systems Documentation](https://docs.nvidia.com/nsight-systems/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

---
