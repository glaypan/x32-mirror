"""Cloud backup: snapshots to object storage / WebDAV / local dir.

Snapshot = JSON dump of every mirrored path value (from the engine's
live state cache). Upload targets:
- "s3"     : any S3-compatible store (AWS S3, Aliyun OSS S3-mode,
             Tencent COS S3-mode, MinIO, Backblaze B2) via SigV4 PUT
- "webdav" : Nextcloud / Synology / ADrive etc. via HTTP PUT + Basic auth
- "local"  : a local/NAS directory (also used by the offline self test)

Layout:  <prefix>/snapshots/<node>/<ts>.json   rolling history
         <prefix>/latest.json                  always the newest snapshot

Stdlib only (urllib + hmac for AWS SigV4).
"""

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request

log = logging.getLogger("x32mirror.cloud")


def snapshot_name(node: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"snapshots/{node}/{ts}.json"


def snapshot_bytes(snap: dict) -> bytes:
    return json.dumps(snap, ensure_ascii=False, sort_keys=True).encode("utf-8")


def load_snapshot(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def upload(cfg: dict, body: bytes, key: str):
    """Upload `body` to cfg["prefix"] + "/" + key. Returns True on success."""
    prefix = (cfg.get("prefix") or "x32mirror").strip("/")
    remote = f"{prefix}/{key}"
    provider = cfg.get("provider", "s3")
    if provider == "local":
        path = _local_path(cfg, remote)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body)
        return True
    if provider == "webdav":
        _webdav_request(cfg, remote, body)
        return True
    if provider == "s3":
        _s3_request(cfg, remote, body)
        return True
    raise ValueError(f"unknown cloud provider: {provider}")


def download_latest(cfg: dict):
    """Fetch <prefix>/latest.json; returns bytes or None if missing."""
    prefix = (cfg.get("prefix") or "x32mirror").strip("/")
    remote = f"{prefix}/latest.json"
    provider = cfg.get("provider", "s3")
    try:
        if provider == "local":
            path = _local_path(cfg, remote)
            if not os.path.exists(path):
                return None
            with open(path, "rb") as fh:
                return fh.read()
        if provider == "webdav":
            return _webdav_request(cfg, remote, None)
        if provider == "s3":
            return _s3_request(cfg, remote, None)
    except Exception as exc:  # noqa: BLE001
        log.warning("cloud download failed: %s", exc)
        return None
    raise ValueError(f"unknown cloud provider: {provider}")


def _local_path(cfg: dict, remote: str) -> str:
    return os.path.join(cfg["dir"], *remote.split("/"))


def _webdav_request(cfg: dict, remote: str, body):
    url = cfg["endpoint"].rstrip("/") + "/" + remote
    req = urllib.request.Request(url, data=body, method="PUT" if body is not None else "GET")
    token = base64.b64encode(
        f'{cfg.get("username", "")}:{cfg.get("password", "")}'.encode("utf-8")).decode("ascii")
    req.add_header("Authorization", "Basic " + token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read() if body is None else None


def _s3_request(cfg: dict, remote: str, body):
    """PUT/GET on an S3-compatible endpoint with AWS Signature V4."""
    endpoint = cfg["endpoint"].rstrip("/")
    bucket = cfg["bucket"]
    host = endpoint.split("://", 1)[1]
    region = cfg.get("region", "us-east-1")
    method = "PUT" if body is not None else "GET"
    payload_hash = hashlib.sha256(body or b"").hexdigest()
    now = datetime.datetime.now(datetime.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amzdate}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = (
        f"{method}\n/{bucket}/{remote}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + cfg.get("secret_key", "")).encode("utf-8"), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "s3")
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    url = f"{endpoint}/{bucket}/{remote}"
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("x-amz-date", amzdate)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header(
        "Authorization",
        f"AWS4-HMAC-SHA256 Credential={cfg.get('access_key', '')}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read() if method == "GET" else None
