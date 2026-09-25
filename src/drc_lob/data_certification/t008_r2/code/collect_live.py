"""Collect public BTC/ETH book snapshots and BBO messages; no account streams."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import ctypes
import gzip
import hashlib
import json
import os
import shutil
import time
import websocket

ROOT=Path(__file__).resolve().parents[1]
DURATION_SECONDS=1800
BYTE_CEILING=256*1024**2
MIN_FREE=50*1024**3
SEED=20260919
if os.name=="nt":
    ctypes.windll.kernel32.SetProcessAffinityMask(ctypes.windll.kernel32.GetCurrentProcess(),1)
START=time.monotonic()
START_UTC=datetime.now(timezone.utc).isoformat()
OUT=ROOT/"data/live_capture.jsonl.gz"
META=ROOT/"evidence/live_capture_status.json"
assert not OUT.exists(), "Preserve every acquisition; choose a new version for a later run."
counts=Counter(); received_bytes=0; sent_bytes=0; connections=0; row=0
uncompressed_bytes=0; errors=[]; first_exchange={}; last_exchange={}; handshake_reserve=0
wire_hash=hashlib.sha256()
def status(state):
    out={"origin":"exploratory_real","route":"official_live_snapshot_pilot","status":state,
      "started_utc":START_UTC,"updated_utc":datetime.now(timezone.utc).isoformat(),
      "elapsed_seconds":time.monotonic()-START,"duration_seconds":DURATION_SECONDS,
      "received_application_bytes":received_bytes,"sent_application_bytes":sent_bytes,
      "application_bytes_total":received_bytes+sent_bytes,
      "transport_accounting_reserve_bytes":handshake_reserve+row*256,
      "budget_charged_bytes":received_bytes+sent_bytes+handshake_reserve+row*256,
      "packet_bytes_exactly_measured":False,"connections":connections,"messages":row,
      "counts":dict(counts),"first_exchange_ms":first_exchange,"last_exchange_ms":last_exchange,
      "uncompressed_envelope_bytes":uncompressed_bytes,"wire_text_sha256_so_far":wire_hash.hexdigest(),
      "errors":errors,"byte_ceiling":BYTE_CEILING,"source":"wss://api.hyperliquid.xyz/ws",
      "time_scope":"exchange-reported millisecond snapshot/BBO times; collected local wall and monotonic receipt times are observations, not synchronized latency estimates",
      "semantics":"sampled authoritative20-level snapshots and block BBO changes; no venue-event completeness claimed",
      "seed":SEED,"code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if OUT.exists():out["compressed_bytes_so_far"]=OUT.stat().st_size
    META.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps({k:out[k] for k in ["status","elapsed_seconds","messages","counts","budget_charged_bytes"]}),flush=True)
def send(ws,payload):
    global sent_bytes
    text=json.dumps(payload,separators=(",",":"))
    ws.send(text);sent_bytes+=len(text.encode())
status("starting")
with gzip.open(OUT,"xt",encoding="utf-8",newline="\n",compresslevel=3) as out:
    while time.monotonic()-START<DURATION_SECONDS and connections<4:
        ws=None
        try:
            if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError("physical_disk_floor_reached")
            connections+=1;handshake_reserve+=65536
            ws=websocket.create_connection("wss://api.hyperliquid.xyz/ws",timeout=10,enable_multithread=False)
            for coin in ["BTC","ETH"]:
                send(ws,{"method":"subscribe","subscription":{"type":"l2Book","coin":coin}})
                send(ws,{"method":"subscribe","subscription":{"type":"bbo","coin":coin}})
            ws.settimeout(5)
            checkpoint=time.monotonic()
            ping=checkpoint
            while time.monotonic()-START<DURATION_SECONDS:
                try:raw=ws.recv()
                except websocket.WebSocketTimeoutException:
                    if time.monotonic()-ping>=20:send(ws,{"method":"ping"});ping=time.monotonic()
                    status("waiting");continue
                if not raw:raise RuntimeError("connection_closed")
                wall=time.time_ns();mono=time.monotonic_ns()
                if isinstance(raw,bytes):raw=raw.decode("utf-8")
                payload=raw.encode();received_bytes+=len(payload);wire_hash.update(payload)
                if received_bytes+sent_bytes+handshake_reserve+row*256>BYTE_CEILING:raise RuntimeError("application_and_reserve_budget_stop")
                msg=json.loads(raw)
                channel=msg.get("channel","unknown");data=msg.get("data",{})
                coin=data.get("coin") if isinstance(data,dict) else None
                key=f"{channel}:{coin or '-'}";counts[key]+=1
                if channel=="error":raise RuntimeError("source_subscription_error:"+str(data)[:150])
                if channel in ["l2Book","bbo"]:
                    if coin not in ["BTC","ETH"]:raise ValueError("unexpected_coin")
                    exchange=int(data["time"]);first_exchange.setdefault(key,exchange);last_exchange[key]=exchange
                record={"source_row_zero_based":row,"connection_id":connections,
                    "received_wall_ns":wall,"received_monotonic_ns":mono,"wire_text":raw}
                line=json.dumps(record,separators=(",",":"))+"\n";out.write(line);uncompressed_bytes+=len(line.encode());row+=1
                if time.monotonic()-ping>=20:send(ws,{"method":"ping"});ping=time.monotonic()
                if time.monotonic()-checkpoint>=30:
                    out.flush();status("collecting");checkpoint=time.monotonic()
                    if shutil.disk_usage(ROOT).free<MIN_FREE:raise RuntimeError("physical_disk_floor_reached")
        except Exception as exc:
            errors.append({"connection_id":connections,"elapsed_seconds":time.monotonic()-START,"type":type(exc).__name__,"message":str(exc)[:250]})
            status("connection_failed")
            if "budget" in str(exc) or "disk_floor" in str(exc):break
            time.sleep(2)
        finally:
            if ws is not None:ws.close()
status("completed" if row>0 and time.monotonic()-START>=DURATION_SECONDS else "stopped")
print("COLLECTOR_EXIT",flush=True)
