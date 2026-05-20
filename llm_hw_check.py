#!/usr/bin/env python3
"""
llm_hw_check.py — Detect local hardware and recommend open-weight LLMs.
No required pip dependencies; psutil is used if available.
"""

import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Force UTF-8 on Windows so box-drawing / check-mark characters render correctly.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def _supports_unicode() -> bool:
    try:
        "✓✗≈─┌┐└┘".encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError, AttributeError):
        return False

_UNICODE = _supports_unicode()

# Box-drawing chars — ASCII fallback when Unicode unavailable
_BOX = {
    "tl": "+" if not _UNICODE else "┌",
    "tr": "+" if not _UNICODE else "┐",
    "bl": "+" if not _UNICODE else "└",
    "br": "+" if not _UNICODE else "┘",
    "h":  "-" if not _UNICODE else "─",
    "v":  "|" if not _UNICODE else "│",
}

# ─── ANSI Color Support ────────────────────────────────────────────────────────

def _win_enable_ansi() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
    except Exception:
        pass
    return False

def _supports_color() -> bool:
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        return _win_enable_ansi()
    return os.environ.get("TERM", "dumb") != "dumb"

_USE_COLOR = _supports_color()

def _c(code: str) -> str:
    return code if _USE_COLOR else ""

class C:
    RESET   = _c("\033[0m")
    BOLD    = _c("\033[1m")
    DIM     = _c("\033[2m")
    GREEN   = _c("\033[92m")
    YELLOW  = _c("\033[93m")
    CYAN    = _c("\033[96m")
    RED     = _c("\033[91m")
    MAGENTA = _c("\033[95m")
    BLUE    = _c("\033[94m")
    WHITE   = _c("\033[97m")

def clr(text: str, *codes: str) -> str:
    if not _USE_COLOR:
        return text
    return "".join(codes) + text + C.RESET

# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class GPU:
    name: str
    vram_mb: int
    driver: str = ""
    compute_cap: str = ""
    vendor: str = ""            # "nvidia" | "amd" | "apple" | "other"
    vram_capped: bool = False   # wmic caps AdapterRAM at ~4 GB

    @property
    def vram_gb(self) -> float:
        return self.vram_mb / 1024.0

@dataclass
class HardwareInfo:
    ram_total_mb: int
    cpu_name: str
    cpu_physical_cores: int
    cpu_logical_threads: int
    gpus: List[GPU] = field(default_factory=list)
    is_apple_silicon: bool = False

    @property
    def ram_total_gb(self) -> float:
        return self.ram_total_mb / 1024.0

# ─── Subprocess Helper ─────────────────────────────────────────────────────────

def _run(cmd: List[str], timeout: int = 10) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None

# ─── CPU / RAM Detection ───────────────────────────────────────────────────────

def _ram_from_psutil() -> int:
    try:
        import psutil
        return psutil.virtual_memory().total // (1024 * 1024)
    except ImportError:
        return 0

def _ram_fallback() -> int:
    s = platform.system()
    if s == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
    elif s == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out:
            try:
                return int(out.strip()) // (1024 * 1024)
            except ValueError:
                pass
    elif s == "Windows":
        out = _run(["wmic", "OS", "get", "TotalVisibleMemorySize", "/value"])
        if out:
            m = re.search(r"TotalVisibleMemorySize=(\d+)", out)
            if m:
                return int(m.group(1)) // 1024
    return 0

def _cores_from_psutil() -> Tuple[int, int]:
    try:
        import psutil
        phys = psutil.cpu_count(logical=False) or 1
        logi = psutil.cpu_count(logical=True) or 1
        return phys, logi
    except ImportError:
        return 0, 0

def _cores_fallback() -> Tuple[int, int]:
    try:
        import multiprocessing
        n = multiprocessing.cpu_count()
        return n, n
    except Exception:
        return 1, 1

def _cpu_name() -> str:
    s = platform.system()
    if s == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    elif s == "Darwin":
        out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out and out.strip():
            return out.strip()
        out = _run(["sysctl", "-n", "hw.model"])
        if out and out.strip():
            return out.strip()
    elif s == "Windows":
        out = _run(["wmic", "cpu", "get", "Name", "/value"])
        if out:
            m = re.search(r"Name=(.+)", out)
            if m:
                return m.group(1).strip()
    return platform.processor() or "Unknown CPU"

def detect_ram_cpu() -> HardwareInfo:
    ram_mb = _ram_from_psutil() or _ram_fallback()
    phys, logi = _cores_from_psutil()
    if not phys:
        phys, logi = _cores_fallback()
    is_apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    return HardwareInfo(
        ram_total_mb=max(ram_mb, 0),
        cpu_name=_cpu_name(),
        cpu_physical_cores=phys,
        cpu_logical_threads=logi,
        is_apple_silicon=is_apple,
    )

# ─── GPU Detection ─────────────────────────────────────────────────────────────

def detect_nvidia_gpus() -> List[GPU]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version,compute_cap",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    gpus: List[GPU] = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            vram_mb = int(parts[1])
        except ValueError:
            continue
        gpus.append(GPU(
            name=parts[0],
            vram_mb=vram_mb,
            driver=parts[2] if len(parts) > 2 else "",
            compute_cap=parts[3] if len(parts) > 3 else "",
            vendor="nvidia",
        ))
    return gpus

def detect_amd_gpus() -> List[GPU]:
    out = _run(["rocm-smi", "--json"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    gpus: List[GPU] = []
    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        name = val.get("Card series") or val.get("Card vendor") or key
        # rocm-smi uses different keys across versions
        vram_raw = (
            val.get("VRAM Total Memory (B)") or
            val.get("vram_size") or
            ""
        )
        if not vram_raw:
            continue
        try:
            vram_bytes = int(str(vram_raw).replace(",", "").strip())
            vram_mb = vram_bytes // (1024 * 1024)
        except ValueError:
            continue
        if vram_mb <= 0:
            continue
        gpus.append(GPU(name=name, vram_mb=vram_mb, vendor="amd"))
    return gpus

def detect_apple_gpu(ram_mb: int) -> List[GPU]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return []
    chip = "Apple Silicon"
    out = _run(["system_profiler", "SPHardwareDataType", "-json"])
    if out:
        try:
            data = json.loads(out)
            hw_list = data.get("SPHardwareDataType", [])
            if hw_list:
                chip = hw_list[0].get("chip_type") or hw_list[0].get("machine_model") or chip
        except Exception:
            pass
    usable_mb = max(0, ram_mb - 4096)  # reserve 4 GB for OS / CPU
    return [GPU(name=chip, vram_mb=usable_mb, vendor="apple")]

def detect_wmic_gpus() -> List[GPU]:
    if platform.system() != "Windows":
        return []
    out = _run(["wmic", "path", "win32_VideoController",
                "get", "Name,AdapterRAM", "/format:csv"])
    if not out:
        return []
    # wmic CSV: Node, AdapterRAM, Name  (alphabetical column order)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    gpus: List[GPU] = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            adapter_ram = int(parts[1].strip())
        except ValueError:
            continue
        name = ",".join(parts[2:]).strip()
        if not name or adapter_ram == 0:
            continue
        vram_mb = adapter_ram // (1024 * 1024)
        capped = 3900 <= vram_mb <= 4100  # wmic hard-caps at 4 GB
        gpus.append(GPU(name=name, vram_mb=vram_mb, vendor="other", vram_capped=capped))
    return gpus

def detect_all_gpus(hw: HardwareInfo) -> List[GPU]:
    gpus = detect_nvidia_gpus()
    if not gpus:
        gpus = detect_amd_gpus()
    if not gpus and hw.is_apple_silicon:
        gpus = detect_apple_gpu(hw.ram_total_mb)
    if not gpus and platform.system() == "Windows":
        gpus = detect_wmic_gpus()
    return gpus

def collect_hardware() -> HardwareInfo:
    hw = detect_ram_cpu()
    hw.gpus = detect_all_gpus(hw)
    return hw

# ─── Model Database ────────────────────────────────────────────────────────────
# VRAM values (GB) include ~1–2 GB KV-cache headroom.
# None = not practical at that quantization level.

MODELS: List[Dict] = [
    # ── Qwen2.5 general ──────────────────────────────────────────────────────
    {"name": "Qwen2.5-0.5B",
     "params_b": 0.5,  "q4": 1.5,  "q8": 2.0,  "fp16": 3.0,
     "cat": "general", "notes": "Runs anywhere; ideal for edge/embedded devices"},
    {"name": "Qwen2.5-1.5B",
     "params_b": 1.5,  "q4": 2.5,  "q8": 3.5,  "fp16": 5.0,
     "cat": "general", "notes": "Solid quality for its size; fast CPU inference"},
    {"name": "Qwen2.5-3B",
     "params_b": 3.0,  "q4": 3.5,  "q8": 5.5,  "fp16": 8.5,
     "cat": "general", "notes": "Good choice for 4–6 GB VRAM devices"},
    {"name": "Qwen2.5-7B",
     "params_b": 7.0,  "q4": 6.0,  "q8": 9.5,  "fp16": 16.0,
     "cat": "general", "notes": "Strong general model; beats many older 13B models"},
    {"name": "Qwen2.5-14B",
     "params_b": 14.0, "q4": 10.0, "q8": 17.0, "fp16": 30.0,
     "cat": "general", "notes": "Near GPT-3.5 level; needs 12+ GB VRAM"},
    {"name": "Qwen2.5-32B",
     "params_b": 32.0, "q4": 22.0, "q8": 36.0, "fp16": None,
     "cat": "general", "notes": "Requires 24+ GB VRAM or CPU offload"},
    {"name": "Qwen2.5-72B",
     "params_b": 72.0, "q4": 45.0, "q8": None,  "fp16": None,
     "cat": "general", "notes": "Near frontier quality; needs multi-GPU or large RAM"},
    # ── Qwen2.5-Coder ────────────────────────────────────────────────────────
    {"name": "Qwen2.5-Coder-1.5B",
     "params_b": 1.5,  "q4": 2.5,  "q8": 3.5,  "fp16": 5.0,
     "cat": "code",    "notes": "Excellent tiny code model; fast on any hardware"},
    {"name": "Qwen2.5-Coder-7B",
     "params_b": 7.0,  "q4": 6.0,  "q8": 9.5,  "fp16": 16.0,
     "cat": "code",    "notes": "Top code model at 7B; strong multi-language support"},
    {"name": "Qwen2.5-Coder-32B",
     "params_b": 32.0, "q4": 22.0, "q8": 36.0, "fp16": None,
     "cat": "code",    "notes": "Competitive with GPT-4 on coding tasks"},
    # ── Llama 3.x ────────────────────────────────────────────────────────────
    {"name": "Llama-3.2-1B",
     "params_b": 1.0,  "q4": 2.0,  "q8": 3.0,  "fp16": 4.0,
     "cat": "general", "notes": "Meta's smallest; good for on-device / edge use"},
    {"name": "Llama-3.2-3B",
     "params_b": 3.0,  "q4": 3.5,  "q8": 5.5,  "fp16": 8.5,
     "cat": "general", "notes": "Efficient 3B; strong instruction following"},
    {"name": "Llama-3.1-8B",
     "params_b": 8.0,  "q4": 6.5,  "q8": 10.0, "fp16": 18.0,
     "cat": "general", "notes": "Widely supported; versatile general-purpose model"},
    {"name": "Llama-3.3-70B",
     "params_b": 70.0, "q4": 44.0, "q8": None,  "fp16": None,
     "cat": "general", "notes": "Top open-weight; needs 2×24 GB GPU or large RAM"},
    # ── Mistral ──────────────────────────────────────────────────────────────
    {"name": "Mistral-7B-v0.3",
     "params_b": 7.0,  "q4": 6.0,  "q8": 9.5,  "fp16": 16.0,
     "cat": "general", "notes": "Fast inference; strong instruction following"},
    {"name": "Mistral-Small-3",
     "params_b": 22.0, "q4": 14.5, "q8": 25.0, "fp16": None,
     "cat": "general", "notes": "Strong mid-size model from Mistral AI"},
    # ── Gemma 2 ──────────────────────────────────────────────────────────────
    {"name": "Gemma-2-2B",
     "params_b": 2.0,  "q4": 2.5,  "q8": 4.0,  "fp16": 6.0,
     "cat": "general", "notes": "Google's smallest; punches above its weight class"},
    {"name": "Gemma-2-9B",
     "params_b": 9.0,  "q4": 7.0,  "q8": 11.5, "fp16": 20.0,
     "cat": "general", "notes": "Excellent quality; beats many 13B models"},
    {"name": "Gemma-2-27B",
     "params_b": 27.0, "q4": 18.0, "q8": 30.0, "fp16": None,
     "cat": "general", "notes": "Near top-tier quality; needs 24 GB GPU for Q4"},
    # ── Phi ──────────────────────────────────────────────────────────────────
    {"name": "Phi-3.5-Mini",
     "params_b": 3.8,  "q4": 4.0,  "q8": 6.0,  "fp16": 10.0,
     "cat": "general", "notes": "Microsoft efficient model; great reasoning and math"},
    {"name": "Phi-4",
     "params_b": 14.0, "q4": 10.0, "q8": 17.0, "fp16": 30.0,
     "cat": "general", "notes": "Strong reasoning; outperforms many larger models"},
]

# ─── Recommendation Logic ──────────────────────────────────────────────────────

QUANTS = [("FP16", "fp16"), ("Q8", "q8"), ("Q4", "q4")]  # best → smallest

@dataclass
class ModelResult:
    model: Dict
    tier: str        # excellent | good | partial | cpu_only | no
    quant: str       # FP16 | Q8 | Q4 | —
    vram_needed_gb: float

def effective_vram_gb(hw: HardwareInfo) -> float:
    if not hw.gpus:
        return 0.0
    gpu = max(hw.gpus, key=lambda g: g.vram_mb)
    if hw.is_apple_silicon:
        return max(gpu.vram_gb, max(0.0, hw.ram_total_gb - 4.0))
    return gpu.vram_gb

def classify_model(model: Dict, vram_gb: float, ram_gb: float) -> ModelResult:
    # GPU tiers: try FP16 → Q8 → Q4 (best quality first)
    for label, key in QUANTS:
        needed = model.get(key)
        if needed is None:
            continue
        if vram_gb >= needed * 1.15:
            return ModelResult(model, "excellent", label, needed)
        if vram_gb >= needed:
            return ModelResult(model, "good", label, needed)

    # Partial GPU (Q4 most practical for partial offload — smallest model on GPU)
    q4 = model.get("q4")
    if q4 and vram_gb >= q4 * 0.5:
        return ModelResult(model, "partial", "Q4", q4)

    # CPU-only (RAM ≥ 1.5× Q4 requirement — needs headroom for OS + inference)
    if q4 and ram_gb >= q4 * 1.5:
        return ModelResult(model, "cpu_only", "Q4", q4)

    # Won't fit at all
    smallest = next((model[k] for _, k in QUANTS if model.get(k) is not None), 999.0)
    return ModelResult(model, "no", "—", smallest)

def recommend(hw: HardwareInfo) -> List[ModelResult]:
    vram = effective_vram_gb(hw)
    ram  = hw.ram_total_gb
    return [classify_model(m, vram, ram) for m in MODELS]

# ─── Formatted Output ──────────────────────────────────────────────────────────

TIER_ICONS = {
    "excellent": ("OK", C.GREEN)  if not _UNICODE else ("✓✓", C.GREEN),
    "good":      (" +", C.GREEN)  if not _UNICODE else (" ✓", C.GREEN),
    "partial":   (" ~", C.YELLOW),
    "cpu_only":  (" ~", C.CYAN)   if not _UNICODE else (" ≈", C.CYAN),
    "no":        (" X", C.RED)    if not _UNICODE else (" ✗", C.RED),
}

def _header(title: str) -> None:
    inner = f" {title} "
    bar   = _BOX["h"] * len(inner)
    tl, tr = _BOX["tl"], _BOX["tr"]
    bl, br = _BOX["bl"], _BOX["br"]
    v = _BOX["v"]
    print(f"\n{clr(tl + bar + tr, C.BLUE)}")
    print(f"{clr(v, C.BLUE)}{clr(inner, C.BOLD + C.WHITE)}{clr(v, C.BLUE)}")
    print(f"{clr(bl + bar + br, C.BLUE)}")

def _model_row(r: ModelResult) -> None:
    icon, color = TIER_ICONS[r.tier]
    m = r.model
    cat_color = C.MAGENTA if m["cat"] == "code" else C.CYAN
    # Pre-pad plain text before colorizing to avoid ANSI width distortion
    name_padded  = m["name"].ljust(22)
    cat_padded   = f"[{m['cat']}]".ljust(9)
    quant_padded = r.quant.ljust(5)
    print(
        f"  {clr(icon, color)}  "
        f"{clr(name_padded, C.BOLD)}"
        f"{clr(cat_padded, cat_color)}  "
        f"{clr(quant_padded, C.YELLOW)}"
        f"~{r.vram_needed_gb:>5.1f} GB  "
        f"{clr(m['notes'], C.DIM)}"
    )

def print_hw_summary(hw: HardwareInfo) -> None:
    _header("System Summary")
    print(f"  {clr('CPU:', C.BOLD)} {hw.cpu_name}")
    print(f"       {hw.cpu_physical_cores} physical cores / {hw.cpu_logical_threads} logical threads")
    print(f"  {clr('RAM:', C.BOLD)} {hw.ram_total_gb:.1f} GB total")

    if hw.gpus:
        label = "GPU:"
        for g in hw.gpus:
            vtag = f" [{g.vendor.upper()}]" if g.vendor not in ("other", "") else ""
            warn = (f"  {clr('(AdapterRAM may be capped at 4 GB)', C.YELLOW)}"
                    if g.vram_capped else "")
            print(f"  {clr(label, C.BOLD)} {g.name}{vtag} — {g.vram_gb:.1f} GB VRAM{warn}")
            label = "    "
            if g.driver:
                info = f"Driver: {g.driver}"
                if g.compute_cap:
                    info += f"  Compute: {g.compute_cap}"
                print(f"       {clr(info, C.DIM)}")
        if hw.is_apple_silicon:
            usable = effective_vram_gb(hw)
            print(f"       {clr(f'Unified memory usable as VRAM: {usable:.1f} GB  (total RAM − 4 GB)', C.DIM)}")
    else:
        print(f"  {clr('GPU:', C.BOLD)} {clr('None detected', C.DIM)}")

def print_model_sections(results: List[ModelResult]) -> None:
    def by_params(lst: List[ModelResult]) -> List[ModelResult]:
        return sorted(lst, key=lambda r: r.model["params_b"], reverse=True)

    gpu_good    = by_params([r for r in results if r.tier in ("excellent", "good")])
    gpu_partial = by_params([r for r in results if r.tier == "partial"])
    cpu_only    = by_params([r for r in results if r.tier == "cpu_only"])
    no_fit      = by_params([r for r in results if r.tier == "no"])

    _header("Will Run Well  (GPU accelerated)")
    if gpu_good:
        for r in gpu_good:
            _model_row(r)
    else:
        print(f"  {clr('None — insufficient VRAM for full GPU inference.', C.DIM)}")
    if gpu_partial:
        print(f"\n  {clr('Partial GPU  (CPU offload — usable but slower):', C.BOLD + C.YELLOW)}")
        for r in gpu_partial:
            _model_row(r)

    _header("CPU Only  (slow but usable)")
    if cpu_only:
        for r in cpu_only:
            _model_row(r)
    else:
        print(f"  {clr('None in the CPU-only tier.', C.DIM)}")

    _header("Too Large for This System")
    if no_fit:
        for r in no_fit:
            _model_row(r)
    else:
        print(f"  {clr('All models can run on this system!', C.GREEN)}")

# ─── Hardware Tips ─────────────────────────────────────────────────────────────

def print_tips(hw: HardwareInfo, results: List[ModelResult]) -> None:
    tips: List[str] = []
    vram = effective_vram_gb(hw)
    gpu  = max(hw.gpus, key=lambda g: g.vram_mb) if hw.gpus else None
    ram  = hw.ram_total_gb

    if hw.is_apple_silicon:
        tips.append(
            f"{clr('Apple Silicon:', C.BOLD)} Use {clr('mlx-lm', C.CYAN)} "
            f"(pip install mlx-lm) for native Metal acceleration — "
            f"significantly faster than llama.cpp on Apple hardware."
        )
        if ram < 16:
            tips.append(
                f"With {ram:.0f} GB unified memory, target models ≤ 7B at Q4 "
                f"for comfortable inference speed (≥10 tok/s)."
            )

    if gpu and gpu.vendor == "amd":
        tips.append(
            f"{clr('AMD GPU:', C.BOLD)} Ensure ROCm is installed and "
            f"PYTORCH_ROCM_ARCH matches your GPU. Build llama.cpp with "
            f"{clr('cmake -DGGML_HIPBLAS=ON', C.DIM)} for GPU acceleration."
        )

    if gpu and gpu.vendor == "nvidia":
        tips.append(
            f"{clr('NVIDIA GPU:', C.BOLD)} Use {clr('Ollama', C.CYAN)} or llama.cpp (CUDA build). "
            f"Load all layers to GPU: {clr('llama-cli -ngl 999 -m model.gguf', C.DIM)}"
        )

    if 0 < vram < 6 and not hw.is_apple_silicon:
        tips.append(
            f"{clr('Low VRAM (<6 GB):', C.BOLD)} Focus on 3B–7B Q4 models. "
            f"7B at 5–6 GB VRAM will partially offload to CPU — "
            f"expect 2–5× slower generation than full GPU inference."
        )

    if gpu is None:
        if ram < 16:
            tips.append(
                f"{clr('No GPU + low RAM:', C.BOLD + C.RED)} CPU-only inference will be very slow. "
                f"Prioritize ≤3B models. Consider a hosted API for heavier workloads."
            )
        else:
            tips.append(
                f"{clr('No GPU:', C.BOLD)} llama.cpp CPU inference runs ~2–5 tok/s for 7B Q4 on a modern CPU. "
                f"Pass {clr('-t <physical-cores>', C.DIM)} to avoid hyperthreading overhead."
            )

    if ram >= 64 and vram < 24:
        tips.append(
            f"High system RAM: llama.cpp CPU/GPU split can run large models (32B+) "
            f"by distributing layers. Tune with {clr('-ngl <n>', C.DIM)} to find the GPU layer sweet spot."
        )

    if gpu and gpu.vram_capped:
        tips.append(
            f"{clr('Note:', C.BOLD + C.YELLOW)} Windows wmic caps AdapterRAM at ~4 GB. "
            f"Your actual VRAM may be higher — check GPU vendor software for the true value."
        )

    runnable = [r for r in results if r.tier in ("excellent", "good")]
    if runnable:
        best = max(runnable, key=lambda r: r.model["params_b"])
        tips.append(
            f"Top pick for this system: {clr(best.model['name'], C.BOLD)} "
            f"@ {clr(best.quant, C.YELLOW)} (~{best.vram_needed_gb:.1f} GB) — "
            f"{best.model['notes']}"
        )
    elif not tips:
        tips.append(
            "Use Ollama (ollama.ai) for the easiest cross-platform model management."
        )

    _header("Tips for Your Hardware")
    for i, tip in enumerate(tips[:5], 1):
        print(f"  {clr(str(i) + '.', C.BOLD)} {tip}")

# ─── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(
        f"\n{clr('llm_hw_check', C.BOLD + C.CYAN)}"
        f"{clr(' — LLM hardware compatibility checker', C.WHITE)}\n"
        f"{clr('  Detecting hardware…', C.DIM)}",
        flush=True,
    )
    hw      = collect_hardware()
    results = recommend(hw)
    print_hw_summary(hw)
    print_model_sections(results)
    print_tips(hw, results)
    print()

if __name__ == "__main__":
    main()
