"""
Instance type → power_kw lookup.

Numbers are rough nameplate / typical-use power draws for common cloud SKUs in
kilowatts. They are deliberately approximations — accurate enough for a
"shift this 4-hour job" comparison, not a billing system.

If the user passes `instance_type`, the optimizer overrides `power_kw` with the
value from this table. If `instance_type` is unknown we raise; callers should
either omit it or hit GET /instance-types first to see valid names.

Dashboard-oriented `preset.*` entries are listed first; legacy `cpu.*` / `gpu.*`
SKUs remain for API compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstanceType:
    name: str
    power_kw: float
    label: str
    category: str  # "cpu" | "gpu" | "training-cluster"


_INSTANCES: list[InstanceType] = [
    # --- User-facing presets (dashboard defaults)
    InstanceType(
        "preset.a100_pcie",
        0.30,
        "Single A100 GPU (PCIe)",
        "gpu",
    ),
    InstanceType(
        "preset.a100_sxm",
        0.40,
        "Single A100 GPU (SXM)",
        "gpu",
    ),
    InstanceType(
        "preset.a100_node8",
        6.00,
        "8× A100 node (full server)",
        "gpu",
    ),
    InstanceType(
        "preset.h100_node8",
        10.00,
        "8× H100 node (full server)",
        "gpu",
    ),
    InstanceType(
        "preset.cluster_multinode",
        32.00,
        "Multi-node training cluster",
        "training-cluster",
    ),
    InstanceType(
        "preset.cpu_node",
        0.50,
        "CPU-only compute node",
        "cpu",
    ),
    # --- Legacy / SKU-style names (existing clients)
    InstanceType("cpu.small",        0.05, "1 vCPU general-purpose VM",                "cpu"),
    InstanceType("cpu.medium",       0.15, "4 vCPU general-purpose VM",                "cpu"),
    InstanceType("cpu.large",        0.40, "16 vCPU general-purpose VM",               "cpu"),
    InstanceType("cpu.xlarge",       1.10, "64 vCPU compute node",                     "cpu"),
    InstanceType("gpu.t4",           0.30, "1× NVIDIA T4 inference VM",                "gpu"),
    InstanceType("gpu.l4",           0.45, "1× NVIDIA L4 inference VM",                "gpu"),
    InstanceType("gpu.a10",          0.65, "1× NVIDIA A10 inference VM",               "gpu"),
    InstanceType("gpu.a100.40g",     1.20, "1× NVIDIA A100 40GB",                      "gpu"),
    InstanceType("gpu.a100.80g.x4",  5.00, "4× NVIDIA A100 80GB training VM",          "gpu"),
    InstanceType("gpu.h100.x1",      2.20, "1× NVIDIA H100 SXM",                       "gpu"),
    InstanceType("gpu.h100.x8",     12.00, "8× NVIDIA H100 SXM training VM",           "gpu"),
    InstanceType("gpu.h100.x64",    96.00, "8-node H100 cluster (64 GPUs)",            "training-cluster"),
]

_BY_NAME: dict[str, InstanceType] = {i.name: i for i in _INSTANCES}


class UnknownInstanceType(ValueError):
    """The instance_type the caller asked for is not in our table."""


def list_instance_types() -> list[InstanceType]:
    return list(_INSTANCES)


def power_kw_for(name: str) -> float:
    inst = _BY_NAME.get(name)
    if inst is None:
        raise UnknownInstanceType(
            f"Unknown instance_type {name!r}. Call GET /instance-types to see "
            f"the supported list, or omit instance_type and pass power_kw directly."
        )
    return inst.power_kw


def get_instance(name: str) -> InstanceType | None:
    return _BY_NAME.get(name)
