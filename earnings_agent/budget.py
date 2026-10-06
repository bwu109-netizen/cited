"""Hard spending cap for evaluation runs.

Every paid model call made under a Budget is first *reserved* with a worst-case cost
(input tokens x input price + max output tokens x output price). If spent + reserved + this
worst case would exceed the cap, BudgetExceeded is raised and nothing is sent. After the call
the reservation is replaced by the actual cost in an append-only ledger (JSONL), so the cap
holds across processes and restarts.

Batches (Anthropic Message Batches) reserve the summed worst case of all their requests before
submission, because a submitted batch cannot be stopped half-way without paying for finished requests.
"""
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, ledger_path, cap_usd):
        self.path = Path(ledger_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = float(cap_usd)

    def _rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def status(self):
        spent = reserved = 0.0
        open_res = {}
        for r in self._rows():
            if r["kind"] == "reserve":
                open_res[r["id"]] = r["usd"]
            elif r["kind"] == "settle":
                open_res.pop(r["id"], None)
                spent += r["usd"]
        reserved = sum(open_res.values())
        return {"cap": self.cap, "spent": spent, "reserved": reserved, "left": self.cap - spent - reserved}

    def _append(self, row):
        row["t"] = time.time()
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    @contextmanager
    def reserve(self, worst_case_usd, label):
        """Reserve the worst case; yields a settle(actual_usd) function. Raises BudgetExceeded up front."""
        st = self.status()
        if worst_case_usd > st["left"]:
            raise BudgetExceeded(f"{label}: worst case ${worst_case_usd:.4f} > left ${st['left']:.4f} "
                                 f"(cap ${self.cap}, spent ${st['spent']:.4f}, reserved ${st['reserved']:.4f})")
        rid = uuid.uuid4().hex
        self._append({"kind": "reserve", "id": rid, "usd": worst_case_usd, "label": label})
        settled = {}

        def settle(actual_usd):
            settled["usd"] = actual_usd
        try:
            yield settle
        finally:
            # if the call failed before reporting a cost, keep the worst case as spent (we may have been billed)
            self._append({"kind": "settle", "id": rid, "usd": settled.get("usd", worst_case_usd), "label": label,
                          "estimated": "usd" not in settled})


def worst_case_usd(input_tokens, max_output_tokens, price_in, price_out):
    return (input_tokens * price_in + max_output_tokens * price_out) / 1e6
