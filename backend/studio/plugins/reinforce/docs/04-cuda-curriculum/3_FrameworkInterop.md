# 3_FrameworkInterop — Framework interop

2 sample document(s), each with the verified *On this box* result and the complete upstream README.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

## 3_FrameworkInterop — Framework interop

Two samples, and the most directly applicable to AI work: how to call a hand-written CUDA kernel from PyTorch and from TensorFlow with gradients intact.

<br>

### customPyTorchKernel

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/3_FrameworkInterop/customPyTorchKernel
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python customPyTorchKernel.py
> ```
>
> **Result** — All tests PASSED including the 3D-tensor case, with autograd working through the custom op.
>
> *Wall time: 1.7 s*
>
> **Notes** — Torch **2.13.0+cu130** installed cleanly and ships sm_120 (`torch.cuda.get_arch_list()` -> `['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']`), so no source build is needed for Blackwell. This is the single most directly useful sample for AI work: it is how you drop a hand-written CUDA kernel into a PyTorch model with gradients intact.

<details>
<summary><b>Full README — customPyTorchKernel</b></summary>

#### Sample: PyTorch Custom GPU Operator

##### Description

This sample demonstrates how to add a custom GPU operation to PyTorch using the `cuda.core` API. It implements a simple square operation (y = x²) to show the complete workflow from CUDA kernel to PyTorch integration with autograd support.

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- PyTorch 2.0+
- cuda-python >= 13.0.0
- cuda-core >=1.0.0

##### Installation

```bash
cd python/3_FrameworkInterop/customPyTorchKernel
pip install -r requirements.txt
```

**Windows users:** The default `torch` wheel on PyPI for Windows is CPU-only and will cause `torch.cuda.is_available()` to return `False`. Install a CUDA-enabled build from PyTorch's wheel index *before* (or after) the command above:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

Replace `cu128` with the wheel suffix matching your installed CUDA driver (e.g. `cu121`, `cu124`, `cu126`, `cu128`). The driver's CUDA version must be >= the wheel's bundled runtime.

##### How to Run

```bash
# Basic usage
python customPyTorchKernel.py

# Test with more elements
python customPyTorchKernel.py --size 1000000

# Use specific GPU
CUDA_VISIBLE_DEVICES=1 python customPyTorchKernel.py
```

##### Expected Output

The sample runs three tests:
1. Forward pass correctness (y = x²)
2. Backward pass correctness (gradient computation)
3. Multi-dimensional tensor support

All tests should pass, confirming the custom operator works correctly with PyTorch's autograd system.

##### Key Concepts

The sample demonstrates:
- Writing CUDA kernels with grid-stride loops
- Runtime kernel compilation with cuda.core
- PyTorch autograd integration via `torch.autograd.Function`
- Stream management using PyTorch's current stream
- Kernel caching for performance

The code is self-documenting with inline comments explaining each step.


</details>

<br>

### customTensorFlowKernel

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/3_FrameworkInterop/customTensorFlowKernel
> source $VENVS/venv-tf/bin/activate      # isolated: TensorFlow
> python customTensorFlowKernel.py
> ```
>
> **Result** — PASSED — custom ReLU operator working, usable inside a `tf.keras.Sequential` via a Lambda layer.
>
> *Wall time: 2.5 s*
>
> **Notes** — Installed into its own venv to keep TensorFlow's pins away from the working environment. It works, but PyTorch's path (above) is far less friction on this stack.

<details>
<summary><b>Full README — customTensorFlowKernel</b></summary>

#### Sample: TensorFlow Custom GPU Operator

##### Description

Learn how to add a custom GPU operation to TensorFlow using `cuda.core` with `tf.py_function`. This sample implements a custom **ReLU operation** (y = max(0, x)) for rapid prototyping of GPU operations.

##### Key Question Answered

**Q: How do I add a custom GPU op to TensorFlow?**

**A:** Use `tf.py_function` to wrap cuda.core kernels:
1. Write CUDA kernels (forward + backward) with grid-stride loops
2. Compile them with cuda.core
3. Wrap in Python functions
4. Use `tf.py_function` to call from TensorFlow
5. Register gradients with `@tf.custom_gradient`

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- TensorFlow 2.10+
- cuda-python >= 13.0.0
- cuda-core >=1.0.0 (required for LEGACY_DEFAULT_STREAM)
- numpy >= 2.3.2
- CuPy (for device pointer access)

##### Installation

```bash
cd python/3_FrameworkInterop/customTensorFlowKernel
pip install -r requirements.txt
```

##### How to Run

```bash
python customTensorFlowKernel.py
python customTensorFlowKernel.py --size 1000000
```

##### Usage Example

```python
import tensorflow as tf
from customTensorFlowKernel import custom_relu

# Simple usage
x = tf.random.normal([100], dtype=tf.float32)
y = custom_relu(x)

# In a Keras model
model = tf.keras.Sequential([
    tf.keras.layers.Dense(128),
    tf.keras.layers.Lambda(custom_relu),
    tf.keras.layers.Dense(10)
])
```

##### Key Concepts

- **tf.py_function**: Bridges TensorFlow and Python code using cuda.core (has overhead, not XLA-compatible)
- **@tf.custom_gradient**: Registers custom backward pass
- **cuda.core**: Primary GPU manager (device, stream, kernel compilation)
- **CuPy**: Internal helper for device pointer access only

##### Production Alternatives

This sample is for rapid prototyping. For production:
- **TensorFlow C++ Custom Op**: Full performance, XLA compatible
- **XLA Custom Calls**: For XLA-compiled models
- See TensorFlow documentation for details

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [TensorFlow tf.py_function](https://www.tensorflow.org/api_docs/python/tf/py_function)
- [TensorFlow @custom_gradient](https://www.tensorflow.org/api_docs/python/tf/custom_gradient)
- [TensorFlow C++ Custom Op Guide](https://www.tensorflow.org/guide/create_op)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

---
