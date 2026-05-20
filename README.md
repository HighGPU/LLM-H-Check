# 🖥️ LLM Hardware Checker

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.7%2B-blue?logo=python&logoColor=white" alt="Python 3.7+"/>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?logo=github" alt="Platform"/>
  <img src="https://img.shields.io/badge/Dependencies-zero-brightgreen" alt="Zero dependencies"/>
  <img src="https://img.shields.io/badge/GPU-NVIDIA%20%7C%20AMD%20%7C%20Apple%20Silicon-orange" alt="GPU support"/>
</p>

<p align="center">
  <b>Instantly know which open-weight LLMs will run on your machine — and how well.</b><br/>
  Detects your CPU, RAM, and GPU, then scores 21 models across every quant tier. No pip installs needed.
</p>

---

## ✨ Features

- **Cross-platform** — Windows, macOS, Linux, Apple Silicon
- **Zero required dependencies** — pure Python stdlib (`psutil` optional for richer CPU info)
- **GPU-aware** — NVIDIA via `nvidia-smi`, AMD via `rocm-smi`, Apple unified memory, Windows `wmic` fallback
- **Quant-tier scoring** — recommends the best quantization level (FP16 / Q8 / Q4) your hardware can handle
- **ANSI-colored output** — auto-disabled on non-TTY and legacy terminals
- **Actionable tips** — hardware-specific advice (MLX for Apple Silicon, ROCm setup for AMD, etc.)

---

## 🚀 Quick Start

```bash
python llm_hw_check.py
```

That's it. No arguments, no config, no installs.

> **Optional:** install `psutil` for more accurate physical core detection
> ```bash
> pip install psutil
> ```

---

## 📸 Example Output

```
llm_hw_check — LLM hardware compatibility checker

┌────────────────┐
│ System Summary │
└────────────────┘
  CPU: Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz
       12 physical cores / 12 logical threads
  RAM: 15.9 GB total
  GPU: NVIDIA GeForce RTX 3060 Laptop GPU [NVIDIA] — 6.0 GB VRAM
       Driver: 596.49  Compute: 8.6

┌──────────────────────────────────┐
│ Will Run Well  (GPU accelerated) │
└──────────────────────────────────┘
  ✓✓  Qwen2.5-0.5B          [general]  FP16  ~  3.0 GB  Runs anywhere; ideal for edge/embedded devices
  ✓✓  Qwen2.5-1.5B          [general]  FP16  ~  5.0 GB  Solid quality for its size; fast CPU inference
   ✓  Qwen2.5-7B             [general]  Q4    ~  6.0 GB  Strong general model; beats many older 13B models
   ✓  Qwen2.5-Coder-7B       [code]     Q4    ~  6.0 GB  Top code model at 7B; strong multi-language support
   ✓  Mistral-7B-v0.3        [general]  Q4    ~  6.0 GB  Fast inference; strong instruction following

  Partial GPU  (CPU offload — usable but slower):
   ~  Llama-3.1-8B           [general]  Q4    ~  6.5 GB  Widely supported; versatile general-purpose model
   ~  Gemma-2-9B             [general]  Q4    ~  7.0 GB  Excellent quality; beats many 13B models

┌───────────────────────────┐
│ Too Large for This System │
└───────────────────────────┘
   ✗  Qwen2.5-72B           [general]  —     ~ 45.0 GB  Near frontier quality; needs multi-GPU or large RAM
   ✗  Llama-3.3-70B         [general]  —     ~ 44.0 GB  Top open-weight; needs 2×24 GB GPU or large RAM

┌────────────────────────┐
│ Tips for Your Hardware │
└────────────────────────┘
  1. NVIDIA GPU: Use Ollama or llama.cpp (CUDA build).
     Load all layers to GPU: llama-cli -ngl 999 -m model.gguf
  2. Top pick: Qwen2.5-7B @ Q4 (~6.0 GB) — beats many older 13B models
```

---

## 🔍 How It Works

### Hardware Detection

| Component | Primary Method | Fallback |
|-----------|---------------|---------|
| RAM | `psutil` | `/proc/meminfo` · `sysctl` · `wmic` |
| CPU name & cores | `psutil` | `/proc/cpuinfo` · `sysctl` · `wmic` |
| NVIDIA GPU | `nvidia-smi --query-gpu` | — |
| AMD GPU | `rocm-smi --json` | — |
| Apple Silicon | `system_profiler SPHardwareDataType` | — |
| Windows GPU | `wmic win32_VideoController` | — |

> Every detection path returns an empty result on failure — the tool **never crashes** on missing tools.

### Recommendation Tiers

| Icon | Tier | Condition |
|------|------|-----------|
| `✓✓` | **Excellent** | VRAM ≥ required × 1.15 — comfortable headroom |
| `✓` | **Good** | VRAM ≥ required — fits cleanly |
| `~` | **Partial GPU** | VRAM ≥ required × 0.5 — layers split to CPU (slower) |
| `≈` | **CPU Only** | No GPU, but RAM ≥ required × 1.5 |
| `✗` | **Too Large** | Won't fit in any configuration |

### Quantization Levels

For each model the tool picks the **highest quality quant** that fits:

```
FP16  →  Q8_0  →  Q4_K_M
(best quality)       (smallest size)
```

All VRAM estimates include **~1–2 GB KV-cache headroom**.

---

## 🤖 Supported Models

| Family | Sizes | Category |
|--------|-------|----------|
| **Qwen2.5** | 0.5B · 1.5B · 3B · 7B · 14B · 32B · 72B | General |
| **Qwen2.5-Coder** | 1.5B · 7B · 32B | Code |
| **Llama 3.x** | 1B · 3B (3.2) · 8B (3.1) · 70B (3.3) | General |
| **Mistral** | 7B v0.3 · Small 3 (22B) | General |
| **Gemma 2** | 2B · 9B · 27B | General |
| **Phi** | 3.5 Mini (3.8B) · 4 (14B) | General |

---

## 🖥️ Platform Notes

| Platform | Status | Notes |
|----------|--------|-------|
| **Windows 10/11** | ✅ Full | ANSI color auto-enabled; Unicode box-drawing with ASCII fallback |
| **macOS (Apple Silicon)** | ✅ Full | Unified memory treated as `RAM − 4 GB` usable VRAM; MLX tip shown |
| **macOS (Intel)** | ✅ Full | Standard CPU/RAM/NVIDIA detection |
| **Linux** | ✅ Full | NVIDIA + AMD ROCm supported |

---

## ▶️ Running the Models

Once you know what fits, pick your runtime:

**[Ollama](https://ollama.ai)** — easiest setup, any platform
```bash
ollama run qwen2.5:7b
ollama run llama3.1:8b
ollama run mistral
```

**[llama.cpp](https://github.com/ggml-org/llama.cpp)** — most flexible, GGUF files from [Hugging Face](https://huggingface.co)
```bash
# NVIDIA — load all layers to GPU
llama-cli -ngl 999 -m Qwen2.5-7B-Instruct-Q4_K_M.gguf

# Partial offload (tune -ngl to match your VRAM)
llama-cli -ngl 20 -m Llama-3.1-8B-Instruct-Q4_K_M.gguf
```

**[mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms)** — Apple Silicon native (recommended over llama.cpp on Mac)
```bash
pip install mlx-lm
mlx_lm.generate --model mlx-community/Qwen2.5-7B-Instruct-4bit --prompt "Hello"
```

---

## ➕ Adding Models

The model database is a plain list of dicts at the top of `llm_hw_check.py`. Add an entry following this schema:

```python
{
    "name":     "Model-Name",
    "params_b": 7.0,           # parameter count in billions
    "q4":       6.0,           # VRAM needed at Q4_K_M (GB), incl. KV-cache headroom
    "q8":       9.5,           # VRAM needed at Q8_0 (GB), or None if impractical
    "fp16":     16.0,          # VRAM needed at FP16 (GB), or None if impractical
    "cat":      "general",     # "general" or "code"
    "notes":    "One-line description shown in output",
}
```

---

<p align="center">
  Made with Python · No frameworks · No fuss
</p>
