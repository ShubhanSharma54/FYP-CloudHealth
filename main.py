from contextlib import asynccontextmanager
from datetime import datetime
import os
import random

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aws_metrics import (
    check_aws_credentials,
    fetch_ec2_metrics,
    generate_mock_metrics,
    get_ec2_client,
    get_ec2_instances,
    get_ebs_volumes,
    get_instance_details,
    get_instance_id,
    get_instance_status,
)
from database import get_db_connection, init_db

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TS_FMT = "%Y-%m-%d %H:%M:%S"

aws_available = False


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_unique(items, value):
    if value not in items:
        items.append(value)


def _to_chart_time(value):
    if isinstance(value, datetime):
        return value.strftime("%b %d, %H:%M")

    if isinstance(value, str):
        for fmt in (TS_FMT, "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt).strftime("%b %d, %H:%M")
            except ValueError:
                continue
        return value

    return ""


def _last_series_value(series):
    if not series:
        return None
    return _as_float(series[-1].get("value"), None)


def _sync_servers_from_aws():
    if not aws_available:
        return

    instances = get_ec2_instances()
    if not instances:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    for inst in instances:
        instance_id = inst.get("id")
        if not instance_id:
            continue

        cursor.execute("SELECT id FROM servers WHERE instance_id = ?", (instance_id,))
        existing = cursor.fetchone()

        # Keep names unique in sqlite, suffix by instance id.
        safe_name = f"{inst.get('name', 'EC2')}-{instance_id[-6:]}"
        region = inst.get("region", AWS_REGION)
        status = inst.get("state", "running")

        if existing:
            cursor.execute(
                """
                UPDATE servers
                SET name = ?, region = ?, status = ?
                WHERE id = ?
                """,
                (safe_name, region, status, existing["id"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO servers (name, instance_id, region, status)
                VALUES (?, ?, ?, ?)
                """,
                (safe_name, instance_id, region, status),
            )

    conn.commit()
    conn.close()


def _resolve_instance_id(server_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT instance_id FROM servers WHERE id = ?", (server_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row["instance_id"]:
        return row["instance_id"]

    if aws_available:
        if server_id == 1:
            return get_instance_id()

        instances = get_ec2_instances()
        if instances and server_id <= len(instances):
            return instances[server_id - 1].get("id")

    return None


def _get_local_rows(server_id, limit=24):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM metrics
        WHERE server_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (server_id, limit),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return list(reversed(rows))


def _get_latest_detailed_metrics(server_id=None, instance_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    if instance_id:
        cursor.execute(
            """
            SELECT * FROM detailed_metrics
            WHERE instance_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (instance_id,),
        )
    elif server_id is not None:
        cursor.execute(
            """
            SELECT * FROM detailed_metrics
            WHERE server_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (server_id,),
        )
    else:
        conn.close()
        return None

    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _build_local_snapshot(server_id, instance_id):
    rows = _get_local_rows(server_id, 24)
    latest = rows[-1] if rows else {}
    detailed = _get_latest_detailed_metrics(server_id=server_id, instance_id=instance_id)

    cpu_value = _as_float(latest.get("cpu_usage"), None)
    if cpu_value is None and detailed:
        cpu_value = _as_float(detailed.get("cpu_percent"), None)

    memory_value = _as_float(latest.get("memory_usage"), None)
    if memory_value is None and detailed:
        memory_value = _as_float(detailed.get("memory_percent"), None)

    disk_value = _as_float(latest.get("disk_usage"), None)
    if disk_value is None and detailed:
        disk_value = _as_float(detailed.get("disk_percent"), None)

    network_in = _as_float(latest.get("network_in"), None)
    if network_in is None and detailed:
        network_in = _as_float(detailed.get("network_in_mb_s"), None)

    network_out = _as_float(latest.get("network_out"), None)
    if network_out is None and detailed:
        network_out = _as_float(detailed.get("network_out_mb_s"), None)

    disk_io_value = _as_float(latest.get("disk_io"), None)
    if disk_io_value is None and detailed:
        disk_io_value = _as_float(detailed.get("disk_read_mb"), 0.0) + _as_float(
            detailed.get("disk_write_mb"), 0.0
        )

    uptime_seconds = _as_int(latest.get("uptime_seconds"), None)
    if uptime_seconds is None and detailed:
        uptime_seconds = _as_int(detailed.get("uptime_seconds"), None)

    cpu_history = [
        {
            "time": _to_chart_time(row.get("timestamp")),
            "cpu": _as_float(row.get("cpu_usage"), 0.0),
        }
        for row in rows
    ]

    memory_history = [
        {
            "time": _to_chart_time(row.get("timestamp")),
            "memory": _as_float(row.get("memory_usage"), 0.0),
        }
        for row in rows
    ]

    network_history = [
        {
            "time": _to_chart_time(row.get("timestamp")),
            "networkIn": _as_float(row.get("network_in"), 0.0),
            "networkOut": _as_float(row.get("network_out"), 0.0),
        }
        for row in rows
    ]

    disk_history = [
        {
            "time": _to_chart_time(row.get("timestamp")),
            "diskIo": _as_float(row.get("disk_io"), 0.0),
            "diskRead": _as_float(row.get("disk_io"), 0.0),
            "diskWrite": _as_float(row.get("disk_io"), 0.0) * 0.6,
        }
        for row in rows
    ]

    last_ts = latest.get("timestamp") if latest else None
    if not last_ts and detailed:
        last_ts = detailed.get("timestamp")

    return {
        "current": {
            "cpu": cpu_value,
            "memory": memory_value,
            "disk": disk_value,
            "network_in": network_in,
            "network_out": network_out,
            "disk_io": disk_io_value,
            "uptime_seconds": uptime_seconds,
        },
        "history": {
            "cpu": cpu_history,
            "memory": memory_history,
            "network": network_history,
            "disk": disk_history,
        },
        "last_local_timestamp": last_ts,
    }


def _build_cloudwatch_snapshot(instance_id):
    if not (aws_available and instance_id):
        return {
            "available": {"cpu": False, "memory": False, "disk": False, "network": False},
            "current": {
                "cpu": None,
                "memory": None,
                "disk": None,
                "network_in": None,
                "network_out": None,
                "disk_io": None,
            },
            "history": {"cpu": [], "memory": [], "network": [], "disk": []},
            "raw": {},
        }

    aws_metrics = fetch_ec2_metrics(instance_id, 24)

    cpu_series = aws_metrics.get("cpu_utilization", [])
    memory_series = aws_metrics.get("memory_usage", [])
    network_in_series = aws_metrics.get("network_in", [])
    network_out_series = aws_metrics.get("network_out", [])
    disk_read_series = aws_metrics.get("disk_read_ops", [])
    disk_write_series = aws_metrics.get("disk_write_ops", [])
    disk_utilization_series = aws_metrics.get("disk_utilization", [])

    cpu_history = [
        {
            "time": _to_chart_time(point.get("timestamp")),
            "cpu": _as_float(point.get("value"), 0.0),
        }
        for point in cpu_series
    ]

    memory_history = [
        {
            "time": _to_chart_time(point.get("timestamp")),
            "memory": _as_float(point.get("value"), 0.0),
        }
        for point in memory_series
    ]

    network_history = []
    max_network = max(len(network_in_series), len(network_out_series))
    for idx in range(max_network):
        in_point = network_in_series[idx] if idx < len(network_in_series) else {}
        out_point = network_out_series[idx] if idx < len(network_out_series) else {}

        timestamp = in_point.get("timestamp") or out_point.get("timestamp")
        network_history.append(
            {
                "time": _to_chart_time(timestamp),
                "networkIn": _as_float(in_point.get("value"), 0.0),
                "networkOut": _as_float(out_point.get("value"), 0.0),
            }
        )

    disk_history = []
    max_disk = max(len(disk_read_series), len(disk_write_series))
    for idx in range(max_disk):
        read_point = disk_read_series[idx] if idx < len(disk_read_series) else {}
        write_point = disk_write_series[idx] if idx < len(disk_write_series) else {}

        timestamp = read_point.get("timestamp") or write_point.get("timestamp")
        read_value = _as_float(read_point.get("value"), 0.0)
        write_value = _as_float(write_point.get("value"), 0.0)
        disk_history.append(
            {
                "time": _to_chart_time(timestamp),
                "diskIo": read_value + write_value,
                "diskRead": read_value,
                "diskWrite": write_value,
            }
        )

    disk_available = len(disk_utilization_series) > 0

    return {
        "available": {
            "cpu": len(cpu_series) > 0,
            "memory": len(memory_series) > 0,
            "disk": disk_available,
            "network": len(network_in_series) > 0 and len(network_out_series) > 0,
        },
        "current": {
            "cpu": _last_series_value(cpu_series),
            "memory": _last_series_value(memory_series),
            "disk": _as_float(aws_metrics.get("disk_usage"), None) if disk_available else None,
            "network_in": _last_series_value(network_in_series),
            "network_out": _last_series_value(network_out_series),
            "disk_io": (
                _last_series_value(disk_read_series) + _last_series_value(disk_write_series)
                if _last_series_value(disk_read_series) is not None
                and _last_series_value(disk_write_series) is not None
                else None
            ),
        },
        "history": {
            "cpu": cpu_history,
            "memory": memory_history,
            "network": network_history,
            "disk": disk_history,
        },
        "raw": aws_metrics,
    }


def _build_mock_snapshot():
    mock = generate_mock_metrics(24)

    cpu_history = [
        {"time": _to_chart_time(point.get("timestamp")), "cpu": _as_float(point.get("value"), 0.0)}
        for point in mock.get("cpu_utilization", [])
    ]

    memory_history = [
        {
            "time": _to_chart_time(point.get("timestamp")),
            "memory": _as_float(point.get("value"), 0.0),
        }
        for point in mock.get("memory_usage", [])
    ]

    network_history = [
        {
            "time": _to_chart_time(point.get("timestamp")),
            "networkIn": _as_float(point.get("network_in"), 0.0),
            "networkOut": _as_float(point.get("network_out"), 0.0),
        }
        for point in mock.get("network_in", [])
    ]

    disk_history = [
        {
            "time": _to_chart_time(point.get("timestamp")),
            "diskIo": _as_float(point.get("disk_io"), 0.0),
            "diskRead": _as_float(point.get("disk_io"), 0.0),
            "diskWrite": _as_float(point.get("disk_io"), 0.0) * 0.6,
        }
        for point in mock.get("disk_io", [])
    ]

    last_network = network_history[-1] if network_history else {}

    return {
        "current": {
            "cpu": _as_float(mock.get("current_cpu"), 0.0),
            "memory": _as_float(mock.get("current_memory"), 0.0),
            "disk": _as_float(mock.get("disk_usage"), 50.0),
            "network_in": _as_float(last_network.get("networkIn"), 0.0),
            "network_out": _as_float(last_network.get("networkOut"), 0.0),
            "disk_io": _as_float(disk_history[-1].get("diskIo"), 0.0) if disk_history else 0.0,
            "uptime_seconds": _as_int(mock.get("uptime_seconds"), 295000),
        },
        "history": {
            "cpu": cpu_history,
            "memory": memory_history,
            "network": network_history,
            "disk": disk_history,
        },
    }


def _pick_metric_field(
    field_name,
    cloudwatch_available,
    cloudwatch_value,
    local_value,
    mock_value,
    cloudwatch_fields,
    fallback_fields,
):
    if cloudwatch_available and cloudwatch_value is not None:
        _append_unique(cloudwatch_fields, field_name)
        return cloudwatch_value

    _append_unique(fallback_fields, field_name)
    if local_value is not None:
        return local_value
    return mock_value


def _normalize_local_payload(payload):
    timestamp = payload.get("timestamp") or datetime.now().strftime(TS_FMT)

    memory_raw = payload.get("memory")
    if isinstance(memory_raw, dict):
        memory_percent = _as_float(memory_raw.get("percent"), 0.0)
        memory_used_mb = _as_float(memory_raw.get("used_mb"), 0.0)
        memory_available_mb = _as_float(memory_raw.get("available_mb"), 0.0)
        memory_total_mb = _as_float(memory_raw.get("total_mb"), 0.0)
    else:
        memory_percent = _as_float(memory_raw, 0.0)
        memory_used_mb = 0.0
        memory_available_mb = 0.0
        memory_total_mb = 0.0

    disk_raw = payload.get("disk")
    if isinstance(disk_raw, dict):
        disk_percent = _as_float(disk_raw.get("percent"), 0.0)
        disk_used_gb = _as_float(disk_raw.get("used_gb"), 0.0)
        disk_free_gb = _as_float(disk_raw.get("free_gb"), 0.0)
        disk_total_gb = _as_float(disk_raw.get("total_gb"), 0.0)
    else:
        disk_percent = _as_float(disk_raw, 0.0)
        disk_used_gb = 0.0
        disk_free_gb = 0.0
        disk_total_gb = 0.0

    network_raw = payload.get("network")
    if isinstance(network_raw, dict):
        network_in = _as_float(network_raw.get("in_mb_s"), 0.0)
        network_out = _as_float(network_raw.get("out_mb_s"), 0.0)
        packets_in = _as_int(network_raw.get("packets_in"), 0)
        packets_out = _as_int(network_raw.get("packets_out"), 0)
        errors_in = _as_int(network_raw.get("errors_in"), 0)
        errors_out = _as_int(network_raw.get("errors_out"), 0)
    else:
        network_in = _as_float(payload.get("network_in"), 0.0)
        network_out = _as_float(payload.get("network_out"), 0.0)
        packets_in = 0
        packets_out = 0
        errors_in = 0
        errors_out = 0

    disk_io_raw = payload.get("disk_io")
    if isinstance(disk_io_raw, dict):
        disk_read_mb = _as_float(disk_io_raw.get("read_mb"), 0.0)
        disk_write_mb = _as_float(disk_io_raw.get("write_mb"), 0.0)
        disk_read_ops = _as_int(disk_io_raw.get("read_ops"), 0)
        disk_write_ops = _as_int(disk_io_raw.get("write_ops"), 0)
        disk_io_simple = disk_read_mb + disk_write_mb
    else:
        disk_io_simple = _as_float(disk_io_raw, 0.0)
        disk_read_mb = disk_io_simple
        disk_write_mb = 0.0
        disk_read_ops = 0
        disk_write_ops = 0

    cpu_cores = payload.get("cpu_cores") if isinstance(payload.get("cpu_cores"), dict) else {}
    swap = payload.get("swap") if isinstance(payload.get("swap"), dict) else {}
    processes = payload.get("processes") if isinstance(payload.get("processes"), dict) else {}

    return {
        "instance_id": payload.get("instance_id") or "",
        "hostname": payload.get("hostname") or "",
        "source": payload.get("source") or "local_agent",
        "timestamp": timestamp,
        "cpu": _as_float(payload.get("cpu"), 0.0),
        "cpu_cores_physical": _as_int(cpu_cores.get("physical_cores"), 0),
        "cpu_cores_logical": _as_int(cpu_cores.get("logical_cores"), 0),
        "memory_percent": memory_percent,
        "memory_used_mb": memory_used_mb,
        "memory_available_mb": memory_available_mb,
        "memory_total_mb": memory_total_mb,
        "swap_percent": _as_float(swap.get("percent"), 0.0),
        "swap_used_mb": _as_float(swap.get("used_mb"), 0.0),
        "swap_total_mb": _as_float(swap.get("total_mb"), 0.0),
        "disk_percent": disk_percent,
        "disk_used_gb": disk_used_gb,
        "disk_free_gb": disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "disk_read_mb": disk_read_mb,
        "disk_write_mb": disk_write_mb,
        "disk_read_ops": disk_read_ops,
        "disk_write_ops": disk_write_ops,
        "network_in": network_in,
        "network_out": network_out,
        "network_packets_in": packets_in,
        "network_packets_out": packets_out,
        "network_errors_in": errors_in,
        "network_errors_out": errors_out,
        "processes_count": _as_int(processes.get("total_processes"), 0),
        "uptime_seconds": _as_int(payload.get("uptime_seconds"), 0),
        "disk_io_simple": disk_io_simple,
    }


def _build_metrics_payload(server_id):
    instance_id = _resolve_instance_id(server_id)

    cloudwatch_snapshot = _build_cloudwatch_snapshot(instance_id)
    local_snapshot = _build_local_snapshot(server_id, instance_id)
    mock_snapshot = _build_mock_snapshot()

    cloudwatch_fields = []
    fallback_fields = []

    cpu = _pick_metric_field(
        "cpu",
        cloudwatch_snapshot["available"]["cpu"],
        cloudwatch_snapshot["current"]["cpu"],
        local_snapshot["current"]["cpu"],
        mock_snapshot["current"]["cpu"],
        cloudwatch_fields,
        fallback_fields,
    )

    memory = _pick_metric_field(
        "memory",
        cloudwatch_snapshot["available"]["memory"],
        cloudwatch_snapshot["current"]["memory"],
        local_snapshot["current"]["memory"],
        mock_snapshot["current"]["memory"],
        cloudwatch_fields,
        fallback_fields,
    )

    disk = _pick_metric_field(
        "disk",
        cloudwatch_snapshot["available"]["disk"],
        cloudwatch_snapshot["current"]["disk"],
        local_snapshot["current"]["disk"],
        mock_snapshot["current"]["disk"],
        cloudwatch_fields,
        fallback_fields,
    )

    if cloudwatch_snapshot["available"]["network"] and (
        cloudwatch_snapshot["current"]["network_in"] is not None
        and cloudwatch_snapshot["current"]["network_out"] is not None
    ):
        network_in = cloudwatch_snapshot["current"]["network_in"]
        network_out = cloudwatch_snapshot["current"]["network_out"]
        _append_unique(cloudwatch_fields, "network")
    else:
        network_in = (
            local_snapshot["current"]["network_in"]
            if local_snapshot["current"]["network_in"] is not None
            else mock_snapshot["current"]["network_in"]
        )
        network_out = (
            local_snapshot["current"]["network_out"]
            if local_snapshot["current"]["network_out"] is not None
            else mock_snapshot["current"]["network_out"]
        )
        _append_unique(fallback_fields, "network")

    disk_io = _pick_metric_field(
        "disk_io",
        cloudwatch_snapshot["current"]["disk_io"] is not None,
        cloudwatch_snapshot["current"]["disk_io"],
        local_snapshot["current"]["disk_io"],
        mock_snapshot["current"]["disk_io"],
        cloudwatch_fields,
        fallback_fields,
    )

    uptime_seconds = (
        local_snapshot["current"]["uptime_seconds"]
        if local_snapshot["current"]["uptime_seconds"] is not None
        else mock_snapshot["current"]["uptime_seconds"]
    )
    _append_unique(fallback_fields, "uptime")

    if cloudwatch_snapshot["available"]["cpu"]:
        cpu_history = cloudwatch_snapshot["history"]["cpu"]
    elif local_snapshot["history"]["cpu"]:
        cpu_history = local_snapshot["history"]["cpu"]
    else:
        cpu_history = mock_snapshot["history"]["cpu"]

    if cloudwatch_snapshot["available"]["memory"]:
        memory_history = cloudwatch_snapshot["history"]["memory"]
    elif local_snapshot["history"]["memory"]:
        memory_history = local_snapshot["history"]["memory"]
    else:
        memory_history = mock_snapshot["history"]["memory"]

    if cloudwatch_snapshot["available"]["network"]:
        network_history = cloudwatch_snapshot["history"]["network"]
    elif local_snapshot["history"]["network"]:
        network_history = local_snapshot["history"]["network"]
    else:
        network_history = mock_snapshot["history"]["network"]

    if cloudwatch_snapshot["history"]["disk"]:
        disk_history = cloudwatch_snapshot["history"]["disk"]
    elif local_snapshot["history"]["disk"]:
        disk_history = local_snapshot["history"]["disk"]
    else:
        disk_history = mock_snapshot["history"]["disk"]

    if cloudwatch_fields and not fallback_fields:
        source = "cloudwatch"
    elif cloudwatch_fields and fallback_fields:
        source = "hybrid"
    else:
        source = "fallback"

    days = uptime_seconds // 86400 if uptime_seconds else 0
    hours = (uptime_seconds % 86400) // 3600 if uptime_seconds else 0

    return {
        "cpu": round(cpu or 0.0, 1),
        "memory": round(memory or 0.0, 1),
        "disk": round(disk or 0.0, 1),
        "network": {
            "in": round(network_in or 0.0, 2),
            "out": round(network_out or 0.0, 2),
        },
        "source": source,
        "cloudwatch_fields": cloudwatch_fields,
        "fallback_fields": fallback_fields,
        # Backward-compatible keys used by existing frontend components.
        "cpu_usage": round(cpu or 0.0, 1),
        "memory_usage": round(memory or 0.0, 1),
        "disk_usage": round(disk or 0.0, 1),
        "uptime_seconds": uptime_seconds,
        "uptime": f"{days} Days {hours} Hours",
        "cpu_history": cpu_history,
        "memory_history": memory_history,
        "network_history": network_history,
        "disk_history": disk_history,
        "instance_id": instance_id,
        "cloudwatch_available": aws_available,
        "last_local_metric_timestamp": local_snapshot["last_local_timestamp"],
        "active_source_mode": source,
        "cpu_credit_balance": cloudwatch_snapshot["raw"].get("cpu_credit_balance", []),
        "network_packets": {
            "in": cloudwatch_snapshot["raw"].get("network_packets_in", []),
            "out": cloudwatch_snapshot["raw"].get("network_packets_out", []),
        },
        "disk_bytes": {
            "read": cloudwatch_snapshot["raw"].get("disk_read_bytes", []),
            "write": cloudwatch_snapshot["raw"].get("disk_write_bytes", []),
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global aws_available
    init_db()
    aws_available = check_aws_credentials()

    if aws_available:
        print(f"[OK] AWS role detected in region {AWS_REGION}")
    else:
        print("[WARN] AWS role unavailable. CloudWatch data may be partial or absent")

    _sync_servers_from_aws()
    yield


app = FastAPI(title="CloudHealth API", version="1.0.0", lifespan=lifespan)

FRONTEND_DIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "frontend", "dist"
)
FRONTEND_INDEX_PATH = os.path.join(FRONTEND_DIST_PATH, "index.html")

if os.path.exists(os.path.join(FRONTEND_DIST_PATH, "assets")):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST_PATH, "assets")),
        name="static",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    if os.path.exists(FRONTEND_INDEX_PATH):
        return FileResponse(FRONTEND_INDEX_PATH)
    return {"error": "Frontend not built. Run 'npm run build' in frontend folder."}


@app.get("/api/servers")
def get_servers():
    _sync_servers_from_aws()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM servers ORDER BY id ASC")
    servers = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return servers


@app.get("/api/metrics")
def get_metrics(server_id: int = 1):
    return _build_metrics_payload(server_id)


@app.get("/api/metrics/cpu")
def get_cpu_metrics(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    return {"data": metrics.get("cpu_history", []), "current": metrics.get("cpu_usage", 0)}


@app.get("/api/metrics/memory")
def get_memory_metrics(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    return {
        "data": metrics.get("memory_history", []),
        "current": metrics.get("memory_usage", 0),
    }


@app.get("/api/metrics/network")
def get_network_metrics(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    return {"data": metrics.get("network_history", [])}


@app.get("/api/metrics/disk")
def get_disk_metrics(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    return {"data": metrics.get("disk_history", [])}


@app.get("/api/alerts")
def get_alerts(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)

    alerts = []
    cpu = metrics.get("cpu_usage", 0)
    memory = metrics.get("memory_usage", 0)
    disk = metrics.get("disk_usage", 0)

    if cpu > 80:
        alerts.append(
            {
                "id": 1,
                "alert_type": "high_cpu",
                "severity": "critical" if cpu > 90 else "warning",
                "message": f"CPU utilization is at {cpu:.1f}%",
                "timestamp": datetime.now().strftime(TS_FMT),
                "metric": "cpu",
            }
        )

    if memory > 80:
        alerts.append(
            {
                "id": 2,
                "alert_type": "high_memory",
                "severity": "critical" if memory > 90 else "warning",
                "message": f"Memory usage is at {memory:.1f}%",
                "timestamp": datetime.now().strftime(TS_FMT),
                "metric": "memory",
            }
        )

    if disk > 80:
        alerts.append(
            {
                "id": 3,
                "alert_type": "high_disk",
                "severity": "critical" if disk > 90 else "warning",
                "message": f"Disk usage is at {disk:.1f}%",
                "timestamp": datetime.now().strftime(TS_FMT),
                "metric": "disk",
            }
        )

    return alerts


@app.get("/api/health")
def get_health(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    instance_id = metrics.get("instance_id")

    details = None
    status = None
    if aws_available and instance_id:
        details = get_instance_details(instance_id)
        status = get_instance_status(get_ec2_client(), instance_id)

    cpu_usage = metrics.get("cpu_usage", 0)
    memory_usage = metrics.get("memory_usage", 0)
    disk_usage = metrics.get("disk_usage", 0)

    return {
        "server": details.get("name", instance_id) if details else f"Server-{server_id}",
        "instance_id": instance_id,
        "instance_type": details.get("instance_type", "N/A") if details else "N/A",
        "status": status.get("status", "running") if status else "running",
        "system_status": status.get("system_status", "unknown") if status else "unknown",
        "response_time": random.randint(40, 140),
        "disk_status": "critical" if disk_usage > 85 else "warning" if disk_usage > 70 else "ok",
        "memory_status": "critical"
        if memory_usage > 90
        else "warning"
        if memory_usage > 75
        else "ok",
        "cpu_status": "critical" if cpu_usage > 90 else "warning" if cpu_usage > 70 else "ok",
        "disk_usage": disk_usage,
        "memory_usage": memory_usage,
        "cpu_usage": cpu_usage,
        "private_ip": details.get("private_ip", "N/A") if details else "N/A",
        "public_ip": details.get("public_ip", "N/A") if details else "N/A",
        "vpc_id": details.get("vpc_id", "N/A") if details else "N/A",
        "source": metrics.get("source", "fallback"),
        "cloudwatch_available": metrics.get("cloudwatch_available", False),
        "last_local_metric_timestamp": metrics.get("last_local_metric_timestamp"),
        "active_source_mode": metrics.get("active_source_mode", "fallback"),
    }


@app.get("/api/status")
def get_status(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)
    return {
        "status": "ok",
        "cloudwatch_available": metrics.get("cloudwatch_available", False),
        "active_source_mode": metrics.get("active_source_mode", "fallback"),
        "last_local_metric_timestamp": metrics.get("last_local_metric_timestamp"),
        "timestamp": datetime.now().strftime(TS_FMT),
    }


@app.get("/api/logs")
def get_logs(server_id: int = 1):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM logs
        WHERE server_id = ?
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        (server_id,),
    )

    logs = []
    for row in cursor.fetchall():
        log = dict(row)
        ts = log.get("timestamp", "")
        if isinstance(ts, str):
            try:
                dt = datetime.strptime(ts, TS_FMT)
                log["timestamp"] = dt.strftime("%b %d, %Y %H:%M")
            except ValueError:
                pass
        logs.append(log)

    conn.close()
    return logs


@app.post("/api/generate-report")
def generate_report(server_id: int = 1):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO logs (server_id, action, status)
        VALUES (?, ?, ?)
        """,
        (server_id, "Report generated", "success"),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Report generated successfully",
        "report_url": f"/api/reports/cloudhealth-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf",
        "timestamp": datetime.now().strftime("%b %d, %Y %H:%M"),
    }


@app.post("/api/download-logs")
def download_logs(server_id: int = 1):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM logs
        WHERE server_id = ?
        ORDER BY timestamp DESC
        LIMIT 100
        """,
        (server_id,),
    )
    logs = cursor.fetchall()

    cursor.execute(
        """
        INSERT INTO logs (server_id, action, status)
        VALUES (?, ?, ?)
        """,
        (server_id, "Log downloaded", "success"),
    )

    conn.commit()

    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_filename = f"cloudhealth-logs-{timestamp}.log"
    log_filepath = os.path.join(log_dir, log_filename)

    with open(log_filepath, "w", encoding="utf-8") as handle:
        handle.write(f"CloudHealth Logs Export - Server ID: {server_id}\n")
        handle.write(f"Generated: {datetime.now().strftime(TS_FMT)}\n")
        handle.write("=" * 60 + "\n\n")

        for row in logs:
            handle.write(
                f"[{row['timestamp']}] [{row['status'].upper()}] {row['action']}\n"
            )

    conn.close()

    return {
        "success": True,
        "message": "Logs downloaded successfully",
        "download_url": f"/api/logs/{log_filename}",
        "timestamp": datetime.now().strftime("%b %d, %Y %H:%M"),
    }


@app.get("/api/logs/{filename}")
def get_log_file(filename: str):
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    filepath = os.path.join(log_dir, filename)
    if os.path.exists(filepath):
        return FileResponse(filepath, filename=filename, media_type="text/plain")
    raise HTTPException(status_code=404, detail="Log file not found")


@app.post("/api/refresh-metrics")
def refresh_metrics(server_id: int = 1):
    metrics = _build_metrics_payload(server_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO metrics (server_id, cpu_usage, memory_usage, disk_usage,
                             network_in, network_out, disk_io, uptime_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            metrics.get("cpu_usage", 0),
            metrics.get("memory_usage", 0),
            metrics.get("disk_usage", 0),
            metrics.get("network", {}).get("in", 0),
            metrics.get("network", {}).get("out", 0),
            _as_float(metrics.get("disk_history", [{}])[-1].get("diskIo"), 0.0)
            if metrics.get("disk_history")
            else 0.0,
            metrics.get("uptime_seconds", 0),
        ),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Metrics refreshed",
        "source": metrics.get("source", "fallback"),
    }


@app.get("/api/instance/details")
def get_instance_details_endpoint(server_id: int = 1):
    if not aws_available:
        return {"error": "AWS not available", "source": "fallback"}

    instance_id = _resolve_instance_id(server_id)
    if not instance_id:
        return {"error": "No instance found", "source": "fallback"}

    details = get_instance_details(instance_id)
    if details:
        details["source"] = "cloudwatch"
        return details
    return {"error": "Failed to get instance details", "source": "fallback"}


@app.get("/api/instance/volumes")
def get_instance_volumes_endpoint(server_id: int = 1):
    if not aws_available:
        return {"volumes": [], "source": "fallback"}

    instance_id = _resolve_instance_id(server_id)
    if not instance_id:
        return {"volumes": [], "error": "No instance found", "source": "fallback"}

    volumes = get_ebs_volumes(instance_id)
    return {"volumes": volumes, "source": "cloudwatch"}


@app.get("/api/instance/status")
def get_instance_status_endpoint(server_id: int = 1):
    if not aws_available:
        return {"error": "AWS not available", "source": "fallback"}

    instance_id = _resolve_instance_id(server_id)
    if not instance_id:
        return {"error": "Instance not found", "source": "fallback"}

    ec2_client = get_ec2_client()
    status = get_instance_status(ec2_client, instance_id)
    status["instance_id"] = instance_id
    status["source"] = "cloudwatch"
    return status


@app.post("/api/local-metrics")
def receive_local_metrics(payload: dict):
    normalized = _normalize_local_payload(payload)
    instance_id = normalized["instance_id"]

    if not instance_id:
        raise HTTPException(status_code=400, detail="instance_id is required")

    hostname = normalized["hostname"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM servers WHERE instance_id = ?", (instance_id,))
    server = cursor.fetchone()

    if server:
        server_id = server["id"]
    else:
        safe_name = f"{(hostname or 'EC2')}-{instance_id[-6:]}"
        cursor.execute(
            """
            INSERT INTO servers (name, instance_id, region, status)
            VALUES (?, ?, ?, ?)
            """,
            (safe_name, instance_id, AWS_REGION, "running"),
        )
        server_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO metrics
        (server_id, cpu_usage, memory_usage, disk_usage, network_in, network_out, disk_io, uptime_seconds, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            normalized["cpu"],
            normalized["memory_percent"],
            normalized["disk_percent"],
            normalized["network_in"],
            normalized["network_out"],
            normalized["disk_io_simple"],
            normalized["uptime_seconds"],
            normalized["timestamp"],
        ),
    )

    cursor.execute(
        """
        INSERT INTO detailed_metrics
        (server_id, instance_id, hostname, source, cpu_percent,
         cpu_cores_physical, cpu_cores_logical, memory_percent,
         memory_used_mb, memory_available_mb, memory_total_mb,
         swap_percent, swap_used_mb, swap_total_mb,
         disk_percent, disk_used_gb, disk_free_gb, disk_total_gb,
         disk_read_mb, disk_write_mb, disk_read_ops, disk_write_ops,
         network_in_mb_s, network_out_mb_s, network_packets_in, network_packets_out,
         network_errors_in, network_errors_out, processes_count, uptime_seconds, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            instance_id,
            normalized["hostname"],
            normalized["source"],
            normalized["cpu"],
            normalized["cpu_cores_physical"],
            normalized["cpu_cores_logical"],
            normalized["memory_percent"],
            normalized["memory_used_mb"],
            normalized["memory_available_mb"],
            normalized["memory_total_mb"],
            normalized["swap_percent"],
            normalized["swap_used_mb"],
            normalized["swap_total_mb"],
            normalized["disk_percent"],
            normalized["disk_used_gb"],
            normalized["disk_free_gb"],
            normalized["disk_total_gb"],
            normalized["disk_read_mb"],
            normalized["disk_write_mb"],
            normalized["disk_read_ops"],
            normalized["disk_write_ops"],
            normalized["network_in"],
            normalized["network_out"],
            normalized["network_packets_in"],
            normalized["network_packets_out"],
            normalized["network_errors_in"],
            normalized["network_errors_out"],
            normalized["processes_count"],
            normalized["uptime_seconds"],
            normalized["timestamp"],
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "server_id": server_id,
        "instance_id": instance_id,
        "message": "Metrics stored",
    }


@app.get("/api/local-metrics")
def get_local_metrics(server_id: int = 1, hours: int = 24):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        raise HTTPException(status_code=404, detail="Server not found")

    cursor.execute(
        """
        SELECT cpu_usage, memory_usage, disk_usage, network_in, network_out,
               disk_io, uptime_seconds, timestamp
        FROM metrics
        WHERE server_id = ? AND timestamp >= datetime('now', '-' || ? || ' hours')
        ORDER BY timestamp ASC
        """,
        (server_id, hours),
    )
    rows = cursor.fetchall()
    conn.close()

    cpu_data = []
    memory_data = []
    network_data = []
    disk_data = []

    for row in rows:
        ts = _to_chart_time(row[7])
        cpu_data.append({"timestamp": ts, "value": row[0]})
        memory_data.append({"timestamp": ts, "value": row[1]})
        network_data.append(
            {
                "timestamp": ts,
                "network_in": row[3],
                "network_out": row[4],
            }
        )
        disk_data.append({"timestamp": ts, "disk_io": row[5]})

    current_cpu = cpu_data[-1]["value"] if cpu_data else 0
    current_memory = memory_data[-1]["value"] if memory_data else 0

    return {
        "cpu_utilization": cpu_data,
        "memory_usage": memory_data,
        "disk_usage": rows[-1][2] if rows else 0,
        "network_in": network_data,
        "network_out": network_data,
        "disk_io": disk_data,
        "uptime_seconds": rows[-1][6] if rows else 0,
        "current_cpu": current_cpu,
        "current_memory": current_memory,
        "source": "local_agent",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)