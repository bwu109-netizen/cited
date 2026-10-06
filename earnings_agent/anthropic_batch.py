"""Anthropic Message Batches client with a hard budget (docs/eval_design.md §4.5).

Flow for one batch:
  1. count input tokens of every request exactly (free /v1/messages/count_tokens, cached on disk)
  2. worst case = sum(input x batch input price + max_tokens x batch output price)
  3. budget.open(worst case) — raises BudgetExceeded before anything is submitted
  4. submit, persist {batch id, reservation id} to a state file (a crash resumes polling, never resubmits)
  5. poll until processing_status == "ended", stream results, cache each reply like a normal call
  6. budget.close(reservation, actual cost from usage)

Errored / canceled / expired requests are not billed by Anthropic and come back with an error.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone

import requests

from . import config
from .llm_client import LLMError, parse_json

API = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"


def _headers():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is empty. Put it in .env")
    return {"x-api-key": key, "anthropic-version": VERSION, "content-type": "application/json"}


def _params(model, system, user, max_tokens):
    p = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": user}]}
    if system:
        p["system"] = system
    # Fable 5.1: adaptive thinking is always on and effort defaults to high -> send neither (§9 decision 2).
    # No temperature: sampling parameters are left at the API defaults for thinking models.
    return p


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def count_tokens(model, system, user):
    path = config.CACHE_DIR / "anthropic_counts" / f"{_key(model, system, user)}.json"
    if path.exists():
        return json.loads(path.read_text())["input_tokens"]
    body = {"model": model, "messages": [{"role": "user", "content": user}]}
    if system:
        body["system"] = system
    r = requests.post(f"{API}/messages/count_tokens", headers=_headers(), json=body, timeout=120)
    if r.status_code != 200:
        raise LLMError(f"count_tokens HTTP {r.status_code}: {r.text[:300]}")
    n = r.json()["input_tokens"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"input_tokens": n}))
    return n


def batch_price(model):
    p = config.PRICES.get(f"{model}:batch")
    if not p:
        raise LLMError(f"no batch price for {model}")
    return p["flat"]


def reply_cache_path(model, system, user, mode, salt=""):
    return config.CACHE_DIR / "llm" / f"{_key('anthropic-batch', model, system, user, mode, salt)}.json"


def run_batch(requests_, budget, label, model="claude-fable-5-1", poll_s=30, timeout_s=6 * 3600):
    """requests_: list of {custom_id, system, user, max_tokens, mode: 'json'|'text', salt}.
    Returns {custom_id: rec} where rec = {data, usage, cost_usd, provider, model, from_cache, error?}."""
    out, todo = {}, []
    for rq in requests_:
        cp = reply_cache_path(model, rq["system"], rq["user"], rq["mode"], rq.get("salt", ""))
        if cp.exists():
            out[rq["custom_id"]] = dict(json.loads(cp.read_text()), from_cache=True)
        else:
            todo.append(rq)
    if not todo:
        return out

    state_path = config.ROOT / "data" / "eval" / "batches" / f"{label}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    req_keys = {rq["custom_id"]: _key(model, rq["system"], rq["user"], rq["mode"], rq.get("salt", ""),
                                      rq["max_tokens"]) for rq in todo}
    if state is not None and state.get("request_keys") != req_keys:
        # a resumed label must carry exactly the same requests; otherwise old results would be filed
        # under new prompts
        raise LLMError(f"batch state {state_path.name} belongs to different requests; use a new label")
    price = batch_price(model)
    if state is None:
        counts = {rq["custom_id"]: count_tokens(model, rq["system"], rq["user"]) for rq in todo}
        worst = sum(counts[rq["custom_id"]] * price["input_miss"] + rq["max_tokens"] * price["output"]
                    for rq in todo) / 1e6
        rid = budget.open(worst, f"batch:{label}")  # BudgetExceeded here -> nothing submitted
        body = {"requests": [{"custom_id": rq["custom_id"],
                              "params": _params(model, rq["system"], rq["user"], rq["max_tokens"])} for rq in todo]}
        try:
            r = requests.post(f"{API}/messages/batches", headers=_headers(), json=body, timeout=300)
            if r.status_code != 200:
                raise LLMError(f"batch create HTTP {r.status_code}: {r.text[:500]}")
        except Exception:
            budget.close(rid, 0.0, f"batch:{label} (not submitted)")
            raise
        state = {"batch_id": r.json()["id"], "reservation": rid, "worst_case_usd": worst, "input_tokens": counts,
                 "request_keys": req_keys,
                 "submitted_at": datetime.now(timezone.utc).isoformat(), "custom_ids": [rq["custom_id"] for rq in todo]}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=1))
        print(f"  [batch] submitted {state['batch_id']} ({len(todo)} requests, worst case ${worst:.2f})", flush=True)

    t0 = time.time()
    while True:
        b = requests.get(f"{API}/messages/batches/{state['batch_id']}", headers=_headers(), timeout=60).json()
        if b.get("processing_status") == "ended":
            break
        if time.time() - t0 > timeout_s:
            raise LLMError(f"batch {state['batch_id']} still {b.get('processing_status')} after {timeout_s}s; "
                           f"rerun to keep polling (reservation stays open)")
        print(f"  [batch] {state['batch_id']} {b.get('processing_status')} {b.get('request_counts')}", flush=True)
        time.sleep(poll_s)

    r = requests.get(b["results_url"], headers=_headers(), timeout=300)
    by_id = {rq["custom_id"]: rq for rq in todo}
    actual = 0.0
    for line in r.text.splitlines():
        if not line.strip():
            continue
        res = json.loads(line)
        cid = res["custom_id"]
        rq = by_id.get(cid)
        if rq is None:
            continue
        if res["result"]["type"] != "succeeded":
            out[cid] = {"error": json.dumps(res["result"])[:500], "data": None, "usage": {}, "cost_usd": 0.0,
                        "provider": "anthropic-batch", "model": model, "from_cache": False}
            continue
        msg = res["result"]["message"]
        text = "".join(blk.get("text", "") for blk in msg.get("content", []) if blk.get("type") == "text")
        u = msg.get("usage", {})
        usage = {"input_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0),
                 "cached_input_tokens": u.get("cache_read_input_tokens", 0),
                 "output_tokens": u.get("output_tokens", 0), "model": f"{model}:batch",
                 "stop_reason": msg.get("stop_reason")}
        cost = ((usage["input_tokens"] - usage["cached_input_tokens"]) * price["input_miss"]
                + usage["cached_input_tokens"] * price["input_hit"] + usage["output_tokens"] * price["output"]) / 1e6
        actual += cost
        try:
            data = parse_json(text) if rq["mode"] == "json" else text
            err = None
        except LLMError as e:
            data, err = None, str(e)
        rec = {"data": data, "raw_text": text, "usage": usage, "cost_usd": cost, "provider": "anthropic-batch",
               "model": model, "batch_id": state["batch_id"], "called_at": state["submitted_at"], "from_cache": False}
        if err:
            rec["error"] = err
        cp = reply_cache_path(model, rq["system"], rq["user"], rq["mode"], rq.get("salt", ""))
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        out[cid] = rec
    if budget.is_open(state["reservation"]):
        budget.close(state["reservation"], actual, f"batch:{label}")
    state.update(ended_at=datetime.now(timezone.utc).isoformat(), actual_usd=actual, request_counts=b.get("request_counts"))
    state_path.write_text(json.dumps(state, indent=1))
    return out
