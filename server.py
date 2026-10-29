from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sys
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATE: dict = {"name": "", "columns": [], "rows": [], "original": [], "undo": [], "fields": {}}
MAX_BODY = 15_000_000
MAX_ROWS = 50_000

# Broad alias dictionary for universal CSV support
ALIASES = {
    "item": [
        "item", "product", "product_name", "item_name", "name", "description", 
        "product_description", "title", "item_title", "part_name", "sku_name", "label",
        "student", "student_name", "employee", "customer", "account", "user", "entity"
    ],
    "stock": [
        "stock", "current_stock", "quantity", "qty", "on_hand", "onhand", "inventory", 
        "units", "units_in_stock", "in_stock", "count", "available", "current_quantity", "balance",
        "math_score", "score", "value", "val", "amount", "rating", "marks", "attendance_pct", "grade"
    ],
    "reorder": [
        "reorder_level", "reorder_point", "minimum_stock", "min_stock", "min", "minimum", 
        "reorder", "reorder_threshold", "reorder_qty", "safety_stock", "threshold", 
        "min_quantity", "min_qty", "target_min", "restock_level", "science_score", 
        "passing_marks", "cutoff", "target", "benchmark", "pass_mark"
    ],
    "sku": ["sku", "product_id", "item_id", "id", "code", "barcode", "part_number", "part_no", "item_no", "student_id", "emp_id", "user_id"],
    "category": ["category", "department", "type", "group", "class", "dept", "section", "grade", "level", "cohort"],
    "price": ["unit_price", "price", "cost", "unit_cost", "retail_price", "rate", "cost_price", "fee"],
}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def detect_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()][:5]
    if not lines:
        return ","
    delimiters = [",", "\t", ";", "|"]
    best_delim = ","
    best_score = -1
    for delim in delimiters:
        counts = [line.count(delim) for line in lines]
        if counts and min(counts) > 0 and min(counts) == max(counts):
            score = counts[0] * 10
        else:
            score = sum(counts)
        if score > best_score:
            best_score = score
            best_delim = delim
    return best_delim


def parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise ValueError("The CSV file is empty.")
    
    delim = detect_delimiter(text[:4096])
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delim)
    raw_columns = [str(c or "").strip() for c in (reader.fieldnames or [])]
    columns = [c for c in raw_columns if c]
    
    if not columns:
        raise ValueError("I couldn't find a valid header row in the CSV.")
    
    seen = {}
    deduped_columns = []
    for c in columns:
        if c in seen:
            seen[c] += 1
            deduped_columns.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 1
            deduped_columns.append(c)
    columns = deduped_columns

    rows = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            break
        if not any(str(v or "").strip() for v in row.values()):
            continue
        cleaned_row = {col: str(row.get(col) or "").strip() for col in columns}
        rows.append(cleaned_row)

    if not rows:
        raise ValueError("The CSV contains headers but no data rows.")
    return columns, rows


def as_number(value: object) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        clean = re.sub(r"[^\d.-]", "", str(value))
        number = float(clean)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def field_map(columns: list[str], rows: list[dict[str, str]] | None = None) -> dict[str, str]:
    normalized_map = {normalize(col): col for col in columns}
    result = {"item": "", "stock": "", "reorder": "", "sku": "", "category": "", "price": ""}

    for role, alias_list in ALIASES.items():
        for alias in alias_list:
            if alias in normalized_map and not result[role]:
                result[role] = normalized_map[alias]
                break

    used_columns = set(result.values())
    unused_cols = [c for c in columns if c not in used_columns]

    if not result["item"]:
        for col in unused_cols:
            n = normalize(col)
            if any(k in n for k in ("item", "product", "name", "desc", "title", "label", "student", "user", "person")):
                result["item"] = col
                unused_cols.remove(col)
                break

    if not result["stock"]:
        for col in unused_cols:
            n = normalize(col)
            if any(k in n for k in ("stock", "qty", "quantity", "count", "hand", "units", "avail", "inventor", "score", "mark", "val", "amount", "pct")):
                result["stock"] = col
                unused_cols.remove(col)
                break

    if not result["reorder"]:
        for col in unused_cols:
            n = normalize(col)
            if any(k in n for k in ("reorder", "min", "threshold", "safety", "restock", "point", "target", "score", "pass", "benchmark")):
                result["reorder"] = col
                unused_cols.remove(col)
                break

    numeric_cols = []
    text_cols = []
    if rows:
        for col in columns:
            is_num = any(as_number(row.get(col)) is not None for row in rows[:20])
            if is_num:
                numeric_cols.append(col)
            else:
                text_cols.append(col)
    else:
        text_cols = columns[:1]
        numeric_cols = columns[1:]

    # Prioritize quantity/threshold columns over years, timestamps, and IDs
    non_year_numeric = [
        c for c in numeric_cols 
        if not any(k in normalize(c) for k in ("year", "yr", "date", "time", "phone", "zip", "postal", "id", "sku"))
    ]
    candidate_numeric = non_year_numeric if non_year_numeric else numeric_cols

    if not result["item"]:
        result["item"] = text_cols[0] if text_cols else columns[0]

    avail_numeric = [c for c in candidate_numeric if c != result["item"]]
    if not result["stock"]:
        if avail_numeric:
            result["stock"] = avail_numeric[0]
            avail_numeric.pop(0)
        elif len(columns) > 1:
            result["stock"] = columns[1]
        else:
            result["stock"] = columns[0]

    if not result["reorder"]:
        if avail_numeric:
            result["reorder"] = avail_numeric[0]
        else:
            result["reorder"] = result["stock"]

    return result


def analyze(rows: list[dict[str, str]], columns: list[str], multiple: float = 2.0, fields: dict | None = None) -> dict:
    if not fields:
        fields = field_map(columns, rows)
    
    low, healthy, review = [], [], []
    total_units = 0.0
    category_counts: dict[str, int] = {}

    for index, row in enumerate(rows):
        stock = as_number(row.get(fields["stock"]))
        reorder = as_number(row.get(fields["reorder"])) if fields["reorder"] != fields["stock"] else (stock or 0.0) * 0.5
        
        if reorder is None and stock is not None:
            reorder = round(stock * 0.5, 1)

        cat = row.get(fields["category"], "General").strip() or "General"
        category_counts[cat] = category_counts.get(cat, 0) + 1

        if stock is None:
            review.append({
                "index": index,
                "item": row.get(fields["item"], f"Row {index+1}"),
                "sku": row.get(fields["sku"], "") if fields["sku"] else "",
                "reason": "Missing or non-numeric stock/value",
                "stock": None,
                "reorder_level": reorder,
            })
            continue

        total_units += stock
        reorder_val = reorder if reorder is not None else 0.0
        qty = max(0, math.ceil(reorder_val * multiple - stock))
        item = {
            "index": index,
            "item": row.get(fields["item"], f"Item {index+1}"),
            "sku": row.get(fields["sku"], "") if fields["sku"] else "",
            "category": cat,
            "stock": stock,
            "reorder_level": reorder_val,
            "order_quantity": qty,
        }
        if stock <= reorder_val:
            low.append(item)
        else:
            healthy.append(item)

    low.sort(key=lambda r: (r["stock"] - r["reorder_level"], str(r["item"]).lower()))
    return {
        "item_column": fields["item"],
        "stock_column": fields["stock"],
        "reorder_column": fields["reorder"],
        "fields": fields,
        "total_items": len(rows),
        "low_count": len(low),
        "out_count": sum(1 for item in low if item["stock"] <= 0),
        "healthy_count": len(healthy),
        "review_count": len(review),
        "total_units": total_units,
        "category_distribution": category_counts,
        "multiple": multiple,
        "low_items": low,
        "review_items": review,
        "healthy_items": healthy,
    }


def local_plan(prompt: str, report: dict | None = None) -> dict:
    lower = prompt.lower()
    
    if any(phrase in lower for phrase in ("prepare reorder", "create reorder", "make reorder", "reorder list", "restock", "order these", "order items", "buy items")):
        if report and report["low_items"]:
            total_qty = sum(item["order_quantity"] for item in report["low_items"])
            return {
                "action": "prepare_reorders",
                "note": f"Found {report['low_count']} item(s) below threshold/reorder levels. Suggested top-up: {total_qty} total units.",
            }
        return {"action": "prepare_reorders", "note": "Prepare suggested quantities for items at or below their target/reorder level."}

    if any(phrase in lower for phrase in ("out of stock", "zero stock", "no stock", "empty", "failing", "zero")):
        if report:
            out_items = [item["item"] for item in report["low_items"] if item["stock"] <= 0]
            if out_items:
                preview = ", ".join(str(x) for x in out_items[:5])
                extra = f" (+{len(out_items)-5} more)" if len(out_items) > 5 else ""
                return {"action": "analyze", "note": f"Critical: {len(out_items)} record(s) have zero/empty values: {preview}{extra}."}
            return {"action": "analyze", "note": "Great! No records currently have zero values."}

    if any(phrase in lower for phrase in ("low stock", "running low", "which items need", "what items need", "need attention", "need restocking", "below threshold", "lowest")):
        if report:
            low_names = [f"{item['item']} ({item['stock']}/{item['reorder_level']})" for item in report["low_items"][:5]]
            return {
                "action": "analyze",
                "note": f"{report['low_count']} item(s) are at or below threshold. Lowest: {', '.join(low_names) if low_names else 'None'}.",
            }

    if any(phrase in lower for phrase in ("review", "data issue", "missing", "invalid", "errors", "check data")):
        if report and report["review_items"]:
            names = [str(item["item"]) for item in report["review_items"][:4]]
            return {"action": "analyze", "note": f"{report['review_count']} item(s) require review due to missing numeric values: {', '.join(names)}."}
        return {"action": "analyze", "note": "All rows have valid numerical values."}

    if report:
        return {
            "action": "analyze",
            "note": f"Dataset contains {report['total_items']} items ({report['total_units']:,.0f} total units/score). {report['low_count']} below threshold ({report['out_count']} at zero).",
        }

    return {"action": "analyze", "note": "I can analyze values against targets or draft restock plans."}


def ai_plan(prompt: str, report: dict) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    context = {k: report[k] for k in ("total_items", "low_count", "out_count", "healthy_count", "review_count") if k in report}
    context["low_items_sample"] = [
        {"item": x["item"], "stock": x["stock"], "reorder": x["reorder_level"], "suggested": x["order_quantity"]}
        for x in report["low_items"][:8]
    ]

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Stockwise, an expert dataset & inventory intelligence agent. "
                    "Analyze the dataset and user request. Choose action: 'analyze' or 'prepare_reorders'. "
                    "Give a concise, helpful note answering the user directly. "
                    "Always output JSON with keys: 'action' and 'note'."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"request": prompt, "summary": context}),
            },
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 250,
    }

    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        res = json.loads(content)
        if res.get("action") not in ("analyze", "prepare_reorders"):
            res["action"] = "analyze"
        return res
    except Exception:
        return None


def make_export(rows: list[dict[str, str]], columns: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


class Handler(BaseHTTPRequestHandler):
    def json_reply(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > MAX_BODY:
            raise ValueError("Request is empty or exceeds limit.")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def download(self, name: str, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/api/status":
            self.json_reply(200, {
                "ai_enabled": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "loaded": bool(STATE["rows"]),
                "row_count": len(STATE["rows"]),
                "name": STATE.get("name", ""),
            })
        elif path == "/api/export/inventory.csv":
            if not STATE["rows"]:
                self.send_error(400, "No data loaded.")
                return
            self.download("dataset-updated.csv", make_export(STATE["rows"], STATE["columns"]))
        elif path == "/api/export/reorder.csv":
            if not STATE["rows"]:
                self.send_error(400, "No data loaded.")
                return
            report = analyze(STATE["rows"], STATE["columns"], fields=STATE.get("fields"))
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(["sku", "item", "category", "current_value", "threshold", "suggested_adjustment", "estimated_cost"])
            fields = report["fields"]
            for item in report["low_items"]:
                price = as_number(STATE["rows"][item["index"]].get(fields["price"])) if fields["price"] else None
                writer.writerow([
                    item["sku"],
                    item["item"],
                    item["category"],
                    item["stock"],
                    item["reorder_level"],
                    item["order_quantity"],
                    round(item["order_quantity"] * price, 2) if price is not None else "",
                ])
            self.download("restock-plan.csv", output.getvalue().encode("utf-8-sig"))
        elif path in {"/", "/index.html"}:
            raw = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        try:
            body = self.read_body()
            if self.path == "/api/upload":
                text, name = body.get("text", ""), str(body.get("name", "dataset.csv"))
                if not isinstance(text, str) or len(text) > 15_000_000:
                    raise ValueError("CSV files must be smaller than 15 MB.")
                columns, rows = parse_csv(text)
                fields = field_map(columns, rows)
                report = analyze(rows, columns, fields=fields)
                STATE.update({
                    "name": Path(name).name[:120],
                    "columns": columns,
                    "rows": rows,
                    "original": deepcopy(rows),
                    "undo": [],
                    "fields": fields,
                })
                self.json_reply(200, {
                    "name": STATE["name"],
                    "columns": columns,
                    "fields": fields,
                    "report": report,
                    "rows": rows[:150],
                    "total_rows": len(rows),
                })
                return

            if self.path == "/api/remap":
                custom = body.get("fields", {})
                if not STATE["rows"]:
                    raise ValueError("No dataset loaded.")
                fields = STATE.get("fields", {})
                fields.update({k: v for k, v in custom.items() if v in STATE["columns"]})
                STATE["fields"] = fields
                report = analyze(STATE["rows"], STATE["columns"], fields=fields)
                self.json_reply(200, {
                    "message": "Column mapping updated.",
                    "fields": fields,
                    "report": report,
                    "rows": STATE["rows"][:150],
                    "total_rows": len(STATE["rows"]),
                    "columns": STATE["columns"],
                })
                return

            if not STATE["rows"]:
                self.json_reply(400, {"error": "Load a CSV dataset first."})
                return

            if self.path == "/api/plan":
                prompt = str(body.get("prompt", "")).strip()
                if not prompt:
                    raise ValueError("Ask a question about your data first.")
                report = analyze(STATE["rows"], STATE["columns"], fields=STATE.get("fields"))
                plan = ai_plan(prompt, report) or local_plan(prompt, report)
                if plan["action"] == "prepare_reorders":
                    for item in report["low_items"]:
                        item["suggested_cost"] = None
                        price_column = report["fields"]["price"]
                        price = as_number(STATE["rows"][item["index"]].get(price_column)) if price_column else None
                        if price is not None:
                            item["suggested_cost"] = round(item["order_quantity"] * price, 2)
                
                self.json_reply(200, {
                    "plan": plan,
                    "report": report,
                    "name": STATE["name"],
                })
                return

            if self.path == "/api/apply-reorders":
                multiple = float(body.get("multiple", 2.0))
                report = analyze(STATE["rows"], STATE["columns"], multiple=multiple, fields=STATE.get("fields"))
                STATE["undo"].append(deepcopy(STATE["rows"]))
                STATE["undo"] = STATE["undo"][-10:]
                for item in report["low_items"]:
                    row = STATE["rows"][item["index"]]
                    row["suggested_order_quantity"] = str(item["order_quantity"])
                    row["reorder_status"] = "Planned"
                for item in report["review_items"]:
                    row = STATE["rows"][item["index"]]
                    row["suggested_order_quantity"] = ""
                    row["reorder_status"] = "Needs review"
                for column in ("suggested_order_quantity", "reorder_status"):
                    if column not in STATE["columns"]:
                        STATE["columns"].append(column)
                self.json_reply(200, {
                    "message": f"Prepared target/reorder quantities ({multiple:.1f}x) for {report['low_count']} item(s).",
                    "rows": STATE["rows"][:150],
                    "total_rows": len(STATE["rows"]),
                    "columns": STATE["columns"],
                    "can_undo": True,
                    "report": analyze(STATE["rows"], STATE["columns"], multiple=multiple, fields=STATE.get("fields")),
                })
                return

            if self.path == "/api/undo":
                if not STATE["undo"]:
                    raise ValueError("There is no action to undo.")
                STATE["rows"] = STATE["undo"].pop()
                STATE["columns"] = list(STATE["rows"][0].keys())
                self.json_reply(200, {
                    "message": "Last change undone.",
                    "rows": STATE["rows"][:150],
                    "total_rows": len(STATE["rows"]),
                    "columns": STATE["columns"],
                    "can_undo": bool(STATE["undo"]),
                    "report": analyze(STATE["rows"], STATE["columns"], fields=STATE.get("fields")),
                })
                return

            if self.path == "/api/reset":
                STATE["undo"].append(deepcopy(STATE["rows"]))
                STATE["undo"] = STATE["undo"][-10:]
                STATE["rows"] = deepcopy(STATE["original"])
                STATE["columns"] = list(STATE["rows"][0].keys())
                self.json_reply(200, {
                    "message": "Restored the original upload.",
                    "rows": STATE["rows"][:150],
                    "total_rows": len(STATE["rows"]),
                    "columns": STATE["columns"],
                    "can_undo": True,
                    "report": analyze(STATE["rows"], STATE["columns"], fields=STATE.get("fields")),
                })
                return

            self.json_reply(404, {"error": "Endpoint not found."})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.json_reply(400, {"error": "Request body must be valid JSON."})
        except ValueError as error:
            self.json_reply(400, {"error": str(error)})
        except Exception as error:
            self.json_reply(500, {"error": f"Internal server error: {str(error)}"})

    def log_message(self, _format: str, *_args: object) -> None:
        pass


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8003"))
    print(f">> Inventory Assistant is running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
