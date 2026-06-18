import logging
import oci
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from app.oci_client import oci_client, OCIClient
from app.config import settings

logger = logging.getLogger("oci-monitor")


async def get_all_instances(client: OCIClient = None, account_id: int = None,
                            account_name: str = None) -> List[Dict[str, Any]]:
    if client is None:
        client = oci_client
    instances = []
    try:
        tenancy = client.tenancy_ocid
        region = client.region
        compartments = client.list_compartments()
        all_compartments = [{"id": tenancy, "name": "root"}]
        for c in compartments:
            all_compartments.append({"id": c.id, "name": c.name})

        for comp in all_compartments:
            raw_instances = client.list_instances(comp["id"])
            for inst in raw_instances:
                instances.append({
                    "id": inst.id,
                    "name": inst.display_name,
                    "status": inst.lifecycle_state,
                    "compartment": comp["name"],
                    "compartment_id": comp["id"],
                    "shape": inst.shape,
                    "region": region,
                    "time_created": inst.time_created.isoformat() if inst.time_created else None,
                    "time_updated": getattr(inst, 'time_updated', None),
                })
    except Exception as e:
        logger.error(f"Error fetching instances: {e}")
    return instances


async def get_instance_metrics(compartment_id: str, instance_id: str,
                               client: OCIClient = None) -> Dict[str, Any]:
    if client is None:
        client = oci_client

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)

    metrics = {
        "cpu_utilization": None,
        "memory_utilization": None,
        "disk_utilization": None,
        "network_bytes_in": None,
        "network_bytes_out": None,
    }

    # OCI SDK 方法名兼容
    summarize = getattr(client.monitoring, 'summarize_metrics_data', None) or getattr(client.monitoring, 'summarize_metric_data', None)

    try:
        cpu_data = summarize(
            compartment_id=compartment_id,
            summarize_metric_data_details=oci.monitoring.models.SummarizeMetricDataDetails(
                namespace="oci_computeagent",
                query=f"CpuUtilization[1m]{{resourceId = \"{instance_id}\"}}.mean()",
                start_time=start.isoformat(), end_time=now.isoformat(), granularity="5m",
            ),
        )
        if cpu_data.data and cpu_data.data[0].aggregated_datapoints:
            metrics["cpu_utilization"] = round(cpu_data.data[0].aggregated_datapoints[-1].value, 1)

        mem_data = summarize(
            compartment_id=compartment_id,
            summarize_metric_data_details=oci.monitoring.models.SummarizeMetricDataDetails(
                namespace="oci_computeagent",
                query=f"MemoryUtilization[1m]{{resourceId = \"{instance_id}\"}}.mean()",
                start_time=start.isoformat(), end_time=now.isoformat(), granularity="5m",
            ),
        )
        if mem_data.data and mem_data.data[0].aggregated_datapoints:
            metrics["memory_utilization"] = round(mem_data.data[0].aggregated_datapoints[-1].value, 1)

        disk_data = summarize(
            compartment_id=compartment_id,
            summarize_metric_data_details=oci.monitoring.models.SummarizeMetricDataDetails(
                namespace="oci_computeagent",
                query=f"DiskUtilization[1m]{{resourceId = \"{instance_id}\", mount = \"/\"}}.mean()",
                start_time=start.isoformat(), end_time=now.isoformat(), granularity="5m",
            ),
        )
        if disk_data.data and disk_data.data[0].aggregated_datapoints:
            metrics["disk_utilization"] = round(disk_data.data[0].aggregated_datapoints[-1].value, 1)

        net_in = summarize(
            compartment_id=compartment_id,
            summarize_metric_data_details=oci.monitoring.models.SummarizeMetricDataDetails(
                namespace="oci_computeagent",
                query=f"NetworkBytesIn[5m]{{resourceId = \"{instance_id}\"}}.sum()",
                start_time=start.isoformat(), end_time=now.isoformat(), granularity="5m",
            ),
        )
        if net_in.data and net_in.data[0].aggregated_datapoints:
            metrics["network_bytes_in"] = sum(v.value for v in net_in.data[0].aggregated_datapoints)

        net_out = summarize(
            compartment_id=compartment_id,
            summarize_metric_data_details=oci.monitoring.models.SummarizeMetricDataDetails(
                namespace="oci_computeagent",
                query=f"NetworkBytesOut[5m]{{resourceId = \"{instance_id}\"}}.sum()",
                start_time=start.isoformat(), end_time=now.isoformat(), granularity="5m",
            ),
        )
        if net_out.data and net_out.data[0].aggregated_datapoints:
            metrics["network_bytes_out"] = sum(v.value for v in net_out.data[0].aggregated_datapoints)

    except Exception as e:
        logger.warning(f"Metrics fetch failed for instance {instance_id}: {e}")

    return metrics


async def check_instance_status_changes(current_instances, previous_states):
    changes = []
    for inst in current_instances:
        iid = inst["id"]
        old_status = previous_states.get(iid)
        if old_status and old_status != inst["status"]:
            changes.append({
                "instance_id": iid,
                "instance_name": inst["name"],
                "compartment": inst["compartment"],
                "account_name": inst.get("account_name", ""),
                "old_status": old_status,
                "new_status": inst["status"],
                "time": datetime.now(timezone.utc).isoformat(),
            })
        previous_states[iid] = inst["status"]
    return changes


async def check_resource_alerts(instances, metrics_map):
    alerts = []
    for inst in instances:
        iid = inst["id"]
        m = metrics_map.get(iid, {})
        if m.get("cpu_utilization") is not None and m["cpu_utilization"] > settings.ALERT_CPU_THRESHOLD:
            alerts.append({"type": "CPU", "instance_id": iid, "instance_name": inst["name"],
                           "value": m["cpu_utilization"], "threshold": settings.ALERT_CPU_THRESHOLD, "severity": "warning"})
        if m.get("memory_utilization") is not None and m["memory_utilization"] > settings.ALERT_MEMORY_THRESHOLD:
            alerts.append({"type": "Memory", "instance_id": iid, "instance_name": inst["name"],
                           "value": m["memory_utilization"], "threshold": settings.ALERT_MEMORY_THRESHOLD, "severity": "warning"})
        if m.get("disk_utilization") is not None and m["disk_utilization"] > settings.ALERT_DISK_THRESHOLD:
            alerts.append({"type": "Disk", "instance_id": iid, "instance_name": inst["name"],
                           "value": m["disk_utilization"], "threshold": settings.ALERT_DISK_THRESHOLD, "severity": "warning"})
    return alerts
