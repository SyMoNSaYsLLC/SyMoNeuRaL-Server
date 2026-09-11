# 01 - Hardware dossier

Measured specifications and raw captures for the target machine (RTX 5070 Ti, Blackwell sm_120). Every figure the engine's benchmark suite compares against originates here.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../docs/symoneural-manual.md`, which remains the canonical single file.

# Part I — Your machine

Measured 2026-08-16. Raw captures in [Appendix A](#appendix-a--raw-hardware-captures).

## The GPU

| Property | Value |
|---|---|
| Name | NVIDIA GeForce RTX 5070 Ti |
| Architecture | Blackwell |
| Compute capability | **12.0** (`sm_120`) |
| SMs × cores | 70 × 128 = **8,960** CUDA cores |
| Global memory | 15,858 MB (15.92 GiB) |
| Memory bus | 256-bit |
| Memory clock | 14,001 MHz |
| **Theoretical DRAM bandwidth** | **896.1 GB/s** |
| L2 cache | 48 MB (50,331,648 bytes) |
| Shared memory / block | 48 KB (102,400 B per SM) |
| Max threads / block · / SM | 1,024 · 1,536 |
| Warp size | 32 |
| Copy engines | 2 (concurrent copy + kernel execution) |
| ECC | Disabled |
| Cooperative kernel launch | Supported |
| Managed memory / UVA | Supported |
| VBIOS | 98.03.58.00.23 |
| Power limit | 300 W default (250–330 W range) |
| Driver | 610.57.04 · CUDA driver 13.3 · runtime 13.3 |
| UUID | GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78 |

## The PCIe ceiling — the most important thing on this page

The original Playbook 01 pasted this and moved on:

```
pcie.link.gen.current, pcie.link.width.current
1, 8
```

That reading is an **idle power-saving state**, not a hardware fact, and treating
it as one is exactly the kind of error this document exists to remove. Here is the
full picture from `nvidia-smi -q`:

```
GPU Link Info
    PCIe Generation
        Max            : 3      <- what this link will ever negotiate
        Current        : 1      <- idle downclock (ASPM)
        Device Current : 1
        Device Max     : 5      <- what the GPU is capable of
        Host Max       : 3      <- what the motherboard offers  <<< the real cap
    Link Width
        Max            : 16x
        Current        : 8x
```

Sampled every 0.4 s during a sustained transfer benchmark, the link trained up to
**Gen 3** and stopped — never Gen 4, never Gen 5, never wider than 8x:

| | idle | under load |
|---|---|---|
| PCIe generation | 1 | **3** (= `Max`, = `Host Max`) |
| Link width | 8x | 8x |
| Power draw | ~12 W | ~57 W |
| Temperature | 44–45 °C | 47–48 °C |

**Gen 3 x8 = 7.88 GB/s theoretical.** Measured, with pinned memory:

| Transfer | Measured | % of Gen 3 x8 peak |
|---|---|---|
| Host → Device (pinned) | **6.94 GB/s** | 88% |
| Host → Device (pageable) | 6.49 GB/s | 82% |
| Device → Host (pinned) | **7.20 GB/s** | 91% |
| Device → Host (pageable) | 7.15 GB/s | 91% |

The link is running at essentially its full Gen 3 x8 capability. There is no
tuning fix — it is the slot. What you can do is stop crossing it: keep working
sets resident in the 15.9 GiB of VRAM.

*(If this is unexpected, it is worth checking whether the card is in the CPU-direct
x16 slot rather than a chipset slot. `Host Max: 3` suggests the platform itself
tops out at Gen 3, but slot choice is the first thing to rule out.)*

## Memory bandwidth — four independent measurements

Since the repository no longer ships `bandwidthTest`, these come from four
different sources, which is a much better check than any single benchmark:

| Source | Measurement | Notes |
|---|---|---|
| CuPy D2D copy, 512 MB | 380.7 GB/s one-way → **761 GB/s DRAM traffic** | a copy reads *and* writes, so DRAM sees 2× |
| `reduction` sample | **752.30 GB/s** | 8.4 M reads, two-stage |
| `reductionMultiBlockCG` sample | **708.92 GB/s** | single launch with `grid.sync()` |
| `alignedTypes` (C++) | 341.5 GB/s one-way → ~683 GB/s | 50 MB working set |

**Use ~750 GB/s as the working figure — 84% of the 896 GB/s theoretical peak.**

### The L2 trap

The same benchmark at different sizes:

| Buffer | D2D reported | What is really happening |
|---|---|---|
| 8 MB | **994 GB/s** | fits entirely in the 48 MB L2 — not a DRAM measurement |
| 32 MB | 493 GB/s | partially cached |
| 128 MB | 380 GB/s | DRAM-bound |
| 512 MB | 380 GB/s | DRAM-bound, stable |

With 48 MB of L2 on this part, **any bandwidth test under ~100 MB is measuring
cache**. This is the single easiest way to publish a wrong number.

## A driver quirk worth knowing

Driver 610 reports stale clocks: `clocks.sm` read **480 MHz while utilization was
100%**, and several clock queries return `Requested functionality has been
deprecated`. Maximum clocks are reported correctly (3,210 MHz SM / 14,001 MHz
memory). **Do not trust `nvidia-smi` instantaneous clock readings on this driver** —
use power draw and achieved throughput as your activity signal instead.

## What this means for AI work

| Situation | Verdict on this box |
|---|---|
| Model fits in 15.9 GiB | Fast. 752 GB/s of weight-reading bandwidth. |
| Model needs CPU offload | Painful. Every offloaded layer crosses a 7 GB/s link. |
| Streaming a dataset from host each step | Bottlenecked on PCIe; pre-stage onto the GPU. |
| Multi-GPU anything | Not testable here — one GPU. |
| Small kernels in a loop | Use CUDA graphs (measured 1.91x). |

Applying the decode-speed formula (`bandwidth ÷ model bytes`) with the **measured**
752 GB/s rather than a spec-sheet number:

| Model @ Q4 | Size | Predicted decode |
|---|---|---|
| 8B | ~4.4 GB | ~170 tok/s |
| 14B | ~7.7 GB | ~98 tok/s |
| 32B | ~17.6 GB | **does not fit** (15.9 GiB) |
| 32B @ IQ2 | ~9.6 GB | ~78 tok/s |

The practical ceiling on this card is a **14B at Q4/Q6, or a 32B at IQ2**.

---

---

# Appendix A — Raw hardware captures

All captured 2026-08-16 on this machine. Nothing in this appendix is edited.

## `systemInfo.py` — driver and device summary

```text

======================================================================
Driver / NVML
======================================================================
CUDA driver version (user-mode): 13.3
CUDA driver version (kernel-mode): 610.57.4
NVML version: (13, 610, 57, 4)
Driver branch: r610_85
Current process: /home/google/Symoneural/cuda-samples/python/.venv/bin/python

======================================================================
Devices detected: 1
======================================================================

-- Device 0 --
Name: NVIDIA GeForce RTX 5070 Ti
UUID: GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78
Compute capability: 12.0
Architecture: BLACKWELL
Brand: GeForce
Memory: total=15.92 GiB, used=936.12 MiB, free=14.57 GiB
PCI: domain=0000 bus=01 device=00 id=00000000:01:00.0
Temperature (GPU sensor): 46 C
Performance state: 0

Done
```

## `deviceQuery.py` — full device properties (Python, cuda.core)

```text
[CUDA Device Query using CUDA Core API]
Detected 1 CUDA Capable device(s)

Device 0: NVIDIA GeForce RTX 5070 Ti
  CUDA Driver Version / Runtime Version          13.3 / 13.3
  CUDA Capability Major/Minor version number:    12.0
  Total amount of global memory:                 15858 MBytes (16628514816 bytes)
  ( 70) Multiprocessors, (128) CUDA Cores/MP:    8960 CUDA Cores
  GPU Max Clock rate:                            2572 MHz (2.57 GHz)
  Memory Clock rate:                             14001 Mhz
  Memory Bus Width:                              256-bit
  L2 Cache Size:                                 50331648 bytes
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
  Device has ECC support:                        Disabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:                                  
     < Default (multiple host threads can use cudaSetDevice() with device simultaneously) >

Done
```

## `deviceQuery` — full device properties (C++, runtime API)

```text
build/cpp/1_Utilities/deviceQuery/deviceQuery Starting...

 CUDA Device Query (Runtime API) version (CUDART static linking)

Detected 1 CUDA Capable device(s)

Device 0: "NVIDIA GeForce RTX 5070 Ti"
  CUDA Driver Version / Runtime Version          13.3 / 13.3
  CUDA Capability Major/Minor version number:    12.0
  Total amount of global memory:                 15858 MBytes (16628514816 bytes)
  (070) Multiprocessors, (128) CUDA Cores/MP:    8960 CUDA Cores
  GPU Max Clock rate:                            2572 MHz (2.57 GHz)
  Memory Clock rate:                             14001 Mhz
  Memory Bus Width:                              256-bit
  L2 Cache Size:                                 50331648 bytes
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
  Max dimension size of a thread block (x,y,z): (1024, 1024, 64)
  Max dimension size of a grid size    (x,y,z): (2147483647, 65535, 65535)
  Maximum memory pitch:                          2147483647 bytes
  Texture alignment:                             512 bytes
  Concurrent copy and kernel execution:          Yes with 2 copy engine(s)
  Run time limit on kernels:                     Yes
  Integrated GPU sharing Host Memory:            No
  Support host page-locked memory mapping:       Yes
  Alignment requirement for Surfaces:            Yes
  Device has ECC support:                        Disabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:
     < Default (multiple host threads can use ::cudaSetDevice() with device simultaneously) >

deviceQuery, CUDA Driver = CUDART, CUDA Driver Version = 13.3, CUDA Runtime Version = 13.3, NumDevs = 1
Result = PASS
```

## `topologyQuery` — CPU/GPU topology

```text
GPU0 <-> CPU:
  * Atomic Supported: no
```

## CuPy bandwidth benchmark — the `bandwidthTest` replacement

```text
Device: NVIDIA GeForce RTX 5070 Ti
Compute capability: 12.0
Memory bus width: 256-bit
Memory clock: 14001 MHz
Theoretical DRAM bandwidth (clock x 2 x bus/8): 896.1 GB/s

    Size |   H2D page    H2D pin |   D2H page    D2H pin |        D2D
    (MB) |       GB/s       GB/s |       GB/s       GB/s |       GB/s
--------------------------------------------------------------------------
       1 |       6.47       6.85 |       4.55       6.84 |     125.21
       8 |       6.50       6.99 |       6.70       7.11 |     994.48
      32 |       6.38       6.95 |       6.93       7.19 |     493.88
     128 |       6.42       6.93 |       7.11       7.16 |     380.30
     512 |       6.49       6.94 |       7.15       7.20 |     380.71

Note: D2D column counts the copy size once (bandwidthTest convention).
      Actual DRAM traffic is 2x that figure (one read + one write).
```

## `alignedTypes` — global-memory copy throughput by type

```text
[./alignedTypes/alignedTypes] - Starting...
GPU Device 0: "Blackwell" with compute capability 12.0

[NVIDIA GeForce RTX 5070 Ti] has 70 MP(s) x 128 (Cores/MP) = 8960 (Cores)
> Compute scaling value = 1.00
> Memory Size = 49999872
Allocating memory...
Generating host input data array...
Uploading input data to GPU memory...
Testing misaligned types...
uint8...
Avg. time: 1.014156 ms / Copy throughput: 45.916012 GB/s.
	TEST OK
uint16...
Avg. time: 0.510344 ms / Copy throughput: 91.244404 GB/s.
	TEST OK
RGBA8_misaligned...
Avg. time: 0.293750 ms / Copy throughput: 158.522592 GB/s.
	TEST OK
LA32_misaligned...
Avg. time: 0.176062 ms / Copy throughput: 264.485685 GB/s.
	TEST OK
RGB32_misaligned...
Avg. time: 0.149500 ms / Copy throughput: 311.478330 GB/s.
	TEST OK
RGBA32_misaligned...
Avg. time: 0.137000 ms / Copy throughput: 339.897893 GB/s.
	TEST OK
Testing aligned types...
RGBA8...
Avg. time: 0.291781 ms / Copy throughput: 159.592195 GB/s.
	TEST OK
I32...
Avg. time: 0.287062 ms / Copy throughput: 162.215581 GB/s.
	TEST OK
LA32...
Avg. time: 0.175437 ms / Copy throughput: 265.427921 GB/s.
	TEST OK
RGB32...
Avg. time: 0.137375 ms / Copy throughput: 338.970049 GB/s.
	TEST OK
RGBA32...
Avg. time: 0.136344 ms / Copy throughput: 341.533883 GB/s.
	TEST OK
RGBA32_2...
Avg. time: 0.139406 ms / Copy throughput: 334.031006 GB/s.
	TEST OK

[alignedTypes] -> Test Results: 0 Failures
Shutting down...
Test passed
```

## `transpose` — shared-memory transpose variants

```text
Transpose Starting...

GPU Device 0: "Blackwell" with compute capability 12.0

> Device 0: "NVIDIA GeForce RTX 5070 Ti"
> SM Capability 12.0 detected:
> [NVIDIA GeForce RTX 5070 Ti] has 70 MP(s) x 128 (Cores/MP) = 8960 (Cores)
> Compute performance scaling factor = 1.00

Matrix size: 1024x1024 (32x32 tiles), tile size: 32x32, block size: 32x16

transpose simple copy       , Throughput = 2186.2688 GB/s, Time = 0.00357 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose shared memory copy, Throughput = 2134.4695 GB/s, Time = 0.00366 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose naive             , Throughput = 372.2734 GB/s, Time = 0.02099 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose coalesced         , Throughput = 999.7977 GB/s, Time = 0.00781 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose optimized         , Throughput = 2189.7983 GB/s, Time = 0.00357 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose coarse-grained    , Throughput = 2164.9431 GB/s, Time = 0.00361 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose fine-grained      , Throughput = 2202.4414 GB/s, Time = 0.00355 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose diagonal          , Throughput = 2043.1888 GB/s, Time = 0.00382 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
Test passed
```

## `UnifiedMemoryPerf` — unified vs explicit copy, by size

```text
GPU Device 0: "Blackwell" with compute capability 12.0

Running ........................................................

Overall Time For matrixMultiplyPerf 

Printing Average of 20 measurements in (ms)
Size_KB	 UMhint	UMhntAs	 UMeasy	  0Copy	MemCopy	CpAsync	CpHpglk	CpPglAs
4	  0.118	  0.121	  0.670	  0.011	  0.024	  0.063	  0.025	  0.020
16	  0.141	  0.128	  1.204	  0.032	  0.034	  0.029	  0.036	  0.034
64	  0.239	  0.237	  1.520	  0.142	  0.077	  0.067	  0.074	  0.067
256	  0.502	  0.454	  3.125	  0.814	  0.238	  0.224	  0.220	  0.208
1024	  1.720	  1.524	  9.429	  6.839	  0.981	  0.944	  0.870	  0.860
4096	  6.522	  6.326	 36.912	 59.704	  4.119	  3.981	  4.001	  4.069
16384	 26.869	 25.143	144.480	409.653	 18.536	 18.360	 18.339	 18.558

NOTE: The CUDA Samples are not meant for performance measurements. Results may vary when GPU Boost is enabled.
```

## `LargeKernelParameter` — 4 KB vs 32 KB kernel parameter limit

```text
Kernel 4KB parameter limit - time (us):57.7569
Kernel 32,764 byte parameter limit - time (us):26.6701
Test passed!
```

## PCIe link state and power, sampled during the transfer benchmark

Sampled every 0.4 s. Columns: gen.current, gen.max, gpu.max, host.max, width.current, width.max, clocks.sm, clocks.mem, power, temp, util.

```text
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.46 W, 44, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 13.48 W, 45, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 28.32 W, 46, 100 %
...
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 13.48 W, 45, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 28.32 W, 46, 100 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 43.51 W, 47, 100 %
...
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.40 W, 45, 1 %
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.55 W, 45, 4 %
```

The `3,` rows are the link trained up under load. `Max` and `Host Max` are both 3 — Gen 3 is the ceiling this platform offers, regardless of the GPU's Gen 5 capability.

## `nvidia-smi -q` — full dump

<details><summary>Expand (369 lines)</summary>

```text

==============NVSMI LOG==============

Timestamp                                              : Sun Aug 16 12:33:54 2026
Driver Version                                         : 610.57.04 [Deprecated; will be removed in CUDA 14.0. Use KMD Version instead]
CUDA Version                                           : 13.3 [Deprecated; will be removed in CUDA 14.0. Use CUDA UMD Version instead]
KMD Version                                            : 610.57.04
CUDA UMD Version                                       : 13.3

Attached GPUs                                          : 1
GPU 00000000:01:00.0
    Product Name                                       : NVIDIA GeForce RTX 5070 Ti
    Product Brand                                      : GeForce
    Product Architecture                               : Blackwell
    Display Mode                                       : Requested functionality has been deprecated
    Display Attached                                   : Yes
    Display Active                                     : Enabled
    Persistence Mode                                   : Enabled
    Addressing Mode                                    : None
    MIG Mode
        Current                                        : N/A
        Pending                                        : N/A
    Accounting Mode                                    : Disabled
    Accounting Mode Buffer Size                        : 4000
    Driver Model
        Current                                        : N/A
        Pending                                        : N/A
    Serial Number                                      : 0
    GPU UUID                                           : GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78
    GPU PDI                                            : 0x6d745dfa53335a17
    Minor Number                                       : 0
    VBIOS Version                                      : 98.03.58.00.23
    MultiGPU Board                                     : No
    Board ID                                           : 0x100
    Board Part Number                                  : N/A
    GPU Part Number                                    : 2C05-300-A1
    FRU Part Number                                    : N/A
    Platform Info
        Chassis Serial Number                          : 
        Slot Number                                    : 0
        Tray Index                                     : 0
        Host ID                                        : 1
        Peer Type                                      : Direct Connected
        Module Id                                      : 1
        GPU Fabric GUID                                : 0x0000000000000000
    Inforom Version
        Image Version                                  : G005.0000.98.01
        OEM Object                                     : 2.1
        ECC Object                                     : N/A
        Power Management Object                        : N/A
    Inforom BBX Object Flush
        Latest Timestamp                               : N/A
        Latest Duration                                : N/A
    Inforom Time Data
        Time Run                                       : N/A
    GPU Operation Mode
        Current                                        : N/A
        Pending                                        : N/A
    GPU C2C Mode                                       : Disabled
    GPU Virtualization Mode
        Virtualization Mode                            : None
        Host VGPU Mode                                 : N/A
        vGPU Heterogeneous Mode                        : N/A
    GPU Recovery Action                                : None
    GSP Firmware Version                               : 610.57.04
    IBMNPU
        Relaxed Ordering Mode                          : N/A
    PCI
        Bus                                            : 0x01
        Device                                         : 0x00
        Domain                                         : 0x0000
        Base Classcode                                 : 0x3
        Sub Classcode                                  : 0x0
        Device Id                                      : 0x2C0510DE
        Bus Id                                         : 00000000:01:00.0
        Sub System Id                                  : 0x143C196E
        GPU Link Info
            PCIe Generation
                Max                                    : 3
                Current                                : 1
                Device Current                         : 1
                Device Max                             : 5
                Host Max                               : 3
            Link Width
                Max                                    : 16x
                Current                                : 8x
        Bridge Chip
            Type                                       : N/A
            Firmware                                   : N/A
        Replays Since Reset                            : 9476
        Replay Number Rollovers                        : 8
        Tx Throughput                                  : 1227 KB/s
        Rx Throughput                                  : 958 KB/s
        Atomic Caps Outbound                           : N/A
        Atomic Caps Inbound                            : FETCHADD_32 FETCHADD_64 SWAP_32 SWAP_64 CAS_32 CAS_64 
    Fan Speed                                          : 0 %
    Performance State                                  : P8
    Clocks Event Reasons
        Idle                                           : Not Active
        Applications Clocks Setting                    : Not Active
        SW Power Cap                                   : Not Active
        HW Slowdown                                    : Not Active
            HW Thermal Slowdown                        : Not Active
            HW Power Brake Slowdown                    : Not Active
        Sync Boost                                     : Not Active
        SW Thermal Slowdown                            : Not Active
        Display Clock Setting                          : Not Active
    Clocks Event Reasons Counters
        SW Power Capping                               : 219139 us
        Sync Boost                                     : 0 us
        SW Thermal Slowdown                            : 0 us
        HW Thermal Slowdown                            : 0 us
        HW Power Braking                               : 0 us
    Sparse Operation Mode                              : N/A
    FB Memory Usage
        Total                                          : 16303 MiB
        Reserved                                       : 445 MiB
        Used                                           : 949 MiB
        Free                                           : 14911 MiB
    BAR1 Memory Usage
        Total                                          : 16384 MiB
        Used                                           : 38 MiB
        Free                                           : 16346 MiB
    Conf Compute Protected Memory Usage
        Total                                          : 0 MiB
        Used                                           : 0 MiB
        Free                                           : 0 MiB
    Compute Mode                                       : Default
    Utilization
        GPU                                            : 3 %
        Memory                                         : 12 %
        Encoder                                        : 0 %
        Decoder                                        : 0 %
        JPEG                                           : 0 %
        OFA                                            : 0 %
    Encoder Stats
        Active Sessions                                : 0
        Average FPS                                    : 0
        Average Latency                                : 0
    FBC Stats
        Active Sessions                                : 0
        Average FPS                                    : 0
        Average Latency                                : 0
    DRAM Encryption Mode
        Current                                        : Disabled
        Pending                                        : Disabled
    ECC Mode
        Current                                        : N/A
        Pending                                        : N/A
    ECC Errors
        Volatile
            SRAM Correctable                           : N/A
            SRAM Uncorrectable Parity                  : N/A
            SRAM Uncorrectable SEC-DED                 : N/A
            DRAM Correctable                           : N/A
            DRAM Uncorrectable                         : N/A
        Aggregate
            SRAM Correctable                           : N/A
            SRAM Uncorrectable Parity                  : N/A
            SRAM Uncorrectable SEC-DED                 : N/A
            DRAM Correctable                           : N/A
            DRAM Uncorrectable                         : N/A
            SRAM Threshold Exceeded                    : N/A
        Aggregate Uncorrectable SRAM Sources
            SRAM L2                                    : N/A
            SRAM SM                                    : N/A
            SRAM Microcontroller                       : N/A
            SRAM PCIE                                  : N/A
            SRAM Other                                 : N/A
        Channel Repair Pending                         : No
        TPC Repair Pending                             : No
        Unrepairable Memory                            : N/A
    Retired Pages
        Single Bit ECC                                 : N/A
        Double Bit ECC                                 : N/A
        Pending Page Blacklist                         : N/A
    Remapped Rows                                      : N/A
    Temperature
        GPU Current Temp                               : 43 C
        GPU Current T.Limit Temp                       : 45 C
        GPU Shutdown T.Limit Temp Specification        : -5 C
        GPU Slowdown T.Limit Temp Specification        : -2 C
        GPU Max Operating T.Limit Temp Specification   : 0 C
        GPU Target Temperature Specification           : N/A
        Memory Current Temp                            : N/A
        Memory Max Operating T.Limit Temp Specification: N/A
    GPU Power Readings
        Average Power Draw                             : 12.24 W
        Instantaneous Power Draw                       : 12.49 W
        GPU Ceiling Power Limit
            Current Power Limit                        : 300.00 W
            Requested Power Limit                      : 300.00 W
            Default Power Limit                        : 300.00 W
        GPU Base Power
            Current Base Power                         : N/A
            Requested Base Power                       : N/A
            Default Base Power                         : N/A
        Min Power Limit                                : 250.00 W
        Max Power Limit                                : 330.00 W
    GPU Memory Power Readings 
        Average Power Draw                             : N/A
        Instantaneous Power Draw                       : N/A
    Module Power Readings
        Average Power Draw                             : N/A
        Instantaneous Power Draw                       : N/A
        Current Power Limit                            : N/A
        Requested Power Limit                          : N/A
        Default Power Limit                            : N/A
        Min Power Limit                                : N/A
        Max Power Limit                                : N/A
    Power Smoothing                                    : N/A
    Workload Power Profiles
        Requested Profiles                             : N/A
        Enforced Profiles                              : N/A
    EDPp Multiplier                                    : N/A
    Clocks
        Graphics                                       : 382 MHz
        SM                                             : 382 MHz
        Memory                                         : 405 MHz
        Video                                          : 652 MHz
    Applications Clocks
        Graphics                                       : Requested functionality has been deprecated
        Memory                                         : Requested functionality has been deprecated
    Default Applications Clocks
        Graphics                                       : Requested functionality has been deprecated
        Memory                                         : Requested functionality has been deprecated
    Deferred Clocks
        Memory                                         : N/A
    Max Clocks
        Graphics                                       : 3210 MHz
        SM                                             : 3210 MHz
        Memory                                         : 14001 MHz
        Video                                          : 3090 MHz
    Max Customer Boost Clocks
        Graphics                                       : N/A
    Clock Policy
        Auto Boost                                     : N/A
        Auto Boost Default                             : N/A
    Fabric
        State                                          : N/A
        Status                                         : N/A
        CliqueId                                       : N/A
        ClusterUUID                                    : N/A
        Health
            Summary                                    : N/A
            Bandwidth                                  : N/A
            Route Recovery in progress                 : N/A
            Route Unhealthy                            : N/A
            Access Timeout Recovery                    : N/A
            Incorrect Configuration                    : N/A
            Partition Assigned                         : N/A
    Processes
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1565
            Type                          : G
            Name                          : /usr/lib/xorg/Xorg
            Used GPU Memory               : 325 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1746
            Type                          : G
            Name                          : /usr/bin/kwalletd6
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1874
            Type                          : G
            Name                          : /usr/bin/ksmserver
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1876
            Type                          : G
            Name                          : /usr/bin/kded6
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1877
            Type                          : G
            Name                          : /usr/bin/kwin_x11
            Used GPU Memory               : 154 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1903
            Type                          : G
            Name                          : /usr/bin/plasmashell
            Used GPU Memory               : 101 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1937
            Type                          : G
            Name                          : /usr/bin/kaccess
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1938
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/polkit-kde-authentication-agent-1
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2108
            Type                          : G
            Name                          : /usr/bin/flameshot
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2149
            Type                          : G
            Name                          : /usr/bin/kdeconnectd
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2188
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/DiscoverNotifier
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2258
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/xdg-desktop-portal-kde
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2412
            Type                          : G
            Name                          : /usr/bin/konsole
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2443
            Type                          : G
            Name                          : /usr/bin/dolphin
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2688
            Type                          : G
            Name                          : /opt/google/chrome/chrome https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A33579%2Fcallback&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afile_upload&code_challenge=8tCeGneQ3EArvQePb5D-ephhItl4SncZLcuMC7IP9Ks&code_challenge_method=S256&state=1WFQ_wXnil70mSAdK1yLOW_gifeX_1nqqGYApHcZSis
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2732
            Type                          : G
            Name                          : /opt/google/chrome/chrome --type=gpu-process --ozone-platform=x11 --crashpad-handler-pid=2695 --enable-crash-reporter=, --change-stack-guard-on-fork=enable --gpu-preferences=YAAAAAAAAAAgAQAEAAAAAAAAAAAAAGAASAAAAAAAAAABAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAMAAAAAAAAAAwAAAAAAAAAAEAAAAAAAAACAAAAAAAAAAMAAAAAQAAAAAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --metrics-shmem-handle=4,i,16145400830234091511,15907328619784115906,262144 --field-trial-handle=3,i,5333793400955105363,123731939696457208,262144 --variations-seed-version=20260816-030043.531000-production --pseudonymization-salt-handle=7,i,14497610698969613647,14539764267232168727,4 --trace-process-track-uuid=3190708988185955192
            Used GPU Memory               : 61 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 5292
            Type                          : G
            Name                          : /usr/bin/dolphin
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 5335
            Type                          : G
            Name                          : /usr/bin/kate
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 6386
            Type                          : G
            Name                          : /usr/bin/konsole
            Used GPU Memory               : 3 MiB
    Capabilities
        EGM                                            : disabled
```

</details>

---
