import logging
from typing import List, Dict, Any
from app.oci_client import oci_client, OCIClient
from app.config import settings

logger = logging.getLogger("oci-monitor")

FREE_TIER_LIMITS = {
    "ARM": {"max_ocpus": 2, "max_memory_gb": 12, "shapes": ["VM.Standard.A1.Flex"]},
    "AMD": {"max_ocpus": 1, "max_memory_gb": 1, "shapes": ["VM.Standard.E2.1.Micro", "VM.Standard.E3.Flex"]},
}


def parse_shape(shape: str) -> Dict[str, Any]:
    info = {"raw": shape, "type": "unknown", "is_flex": False}
    if "A1.Flex" in shape:
        info["type"] = "ARM"; info["is_flex"] = True
    elif "E2.1.Micro" in shape:
        info["type"] = "AMD"
    elif "E3.Flex" in shape or "E4.Flex" in shape or "E5.Flex" in shape:
        info["type"] = "AMD"; info["is_flex"] = True
    elif "VM.Standard" in shape:
        info["type"] = "AMD"
    elif "BM" in shape:
        info["type"] = "BARE_METAL"
    return info


async def check_free_tier_compliance(client: OCIClient = None,
                                     account_id: int = None, account_name: str = None) -> Dict[str, Any]:
    if client is None:
        client = oci_client

    result = {
        "compliant": True, "warnings": [], "instances": [],
        "account_name": account_name or "default",
        "totals": {"arm_ocpus": 0, "arm_memory_gb": 0, "amd_ocpus": 0, "amd_memory_gb": 0},
        "limits": {
            "arm": f"{FREE_TIER_LIMITS['ARM']['max_ocpus']} OCPU / {FREE_TIER_LIMITS['ARM']['max_memory_gb']} GB",
            "amd": f"{FREE_TIER_LIMITS['AMD']['max_ocpus']} OCPU / {FREE_TIER_LIMITS['AMD']['max_memory_gb']} GB",
        },
    }

    try:
        tenancy = client.tenancy_ocid
        compartments = client.list_compartments()
        all_compartments = [{"id": tenancy, "name": "root"}]
        for c in compartments:
            all_compartments.append({"id": c.id, "name": c.name})

        for comp in all_compartments:
            instances = client.list_instances(comp["id"])
            for inst in instances:
                if inst.lifecycle_state in ("TERMINATED",):
                    continue
                shape_info = parse_shape(inst.shape)
                ocpus = 0
                memory_gb = 0
                if hasattr(inst, "shape_config") and inst.shape_config:
                    ocpus = getattr(inst.shape_config, "ocpus", 0) or 0
                    memory_gb = getattr(inst.shape_config, "memory_in_gbs", 0) or 0

                result["instances"].append({
                    "id": inst.id, "name": inst.display_name, "shape": inst.shape,
                    "type": shape_info["type"], "status": inst.lifecycle_state,
                    "ocpus": ocpus, "memory_gb": memory_gb, "compartment": comp["name"],
                })
                if shape_info["type"] == "ARM":
                    result["totals"]["arm_ocpus"] += ocpus
                    result["totals"]["arm_memory_gb"] += memory_gb
                elif shape_info["type"] == "AMD":
                    result["totals"]["amd_ocpus"] += ocpus
                    result["totals"]["amd_memory_gb"] += memory_gb

        arm = result["totals"]
        arm_limit = FREE_TIER_LIMITS["ARM"]
        if arm["arm_ocpus"] > arm_limit["max_ocpus"]:
            result["compliant"] = False
            result["warnings"].append({
                "type": "ARM_OCPU", "severity": "info",
                "message": f"ARM OCPU: {arm['arm_ocpus']} OCPU（新限制 {arm_limit['max_ocpus']}）— 老用户暂未调整",
                "current": arm["arm_ocpus"], "limit": arm_limit["max_ocpus"],
            })
        if arm["arm_memory_gb"] > arm_limit["max_memory_gb"]:
            result["compliant"] = False
            result["warnings"].append({
                "type": "ARM_MEMORY", "severity": "info",
                "message": f"ARM 内存: {arm['arm_memory_gb']} GB（新限制 {arm_limit['max_memory_gb']}）— 老用户暂未调整",
                "current": arm["arm_memory_gb"], "limit": arm_limit["max_memory_gb"],
            })

        amd_limit = FREE_TIER_LIMITS["AMD"]
        if arm["amd_ocpus"] > amd_limit["max_ocpus"]:
            result["compliant"] = False
            result["warnings"].append({
                "type": "AMD_OCPU", "severity": "critical",
                "message": f"AMD OCPU 超标: {arm['amd_ocpus']}（限制 {amd_limit['max_ocpus']}）",
                "current": arm["amd_ocpus"], "limit": amd_limit["max_ocpus"],
            })
        if arm["amd_memory_gb"] > amd_limit["max_memory_gb"]:
            result["compliant"] = False
            result["warnings"].append({
                "type": "AMD_MEMORY", "severity": "critical",
                "message": f"AMD 内存超标: {arm['amd_memory_gb']}（限制 {amd_limit['max_memory_gb']}）",
                "current": arm["amd_memory_gb"], "limit": amd_limit["max_memory_gb"],
            })
    except Exception as e:
        logger.error(f"Free tier check failed: {e}")
        result["warnings"].append({"type": "CHECK_FAILED", "severity": "error", "message": f"检查失败: {e}"})

    return result
