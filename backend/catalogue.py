"""Catalogue rules: category-specific attributes, variants, package data, compliance documents and CSV import/export.

Attributes are validated per PILLAR: a saree carries fabric/weave, skincare carries ingredients/expiry, and so on. A field that
does not belong to the product's pillar is rejected instead of being silently stored, so irrelevant fields never creep in.
The four pillars are locked; sub-categories are free text within a pillar.
"""
import csv
import io
import re
from datetime import date
from typing import Dict, List, Optional

from validators import safe_image_refs

PILLARS = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"]

# key -> ("text" | "number" | "date", max_length_or_max_value)
ATTRIBUTE_SPECS: Dict[str, Dict[str, tuple]] = {
    "Sarees": {"fabric": ("text", 60), "weave_style": ("text", 60), "colour": ("text", 40), "length_m": ("number", 20),
               "care_instructions": ("text", 300), "origin": ("text", 80), "included_accessories": ("text", 120)},
    "Fashion Products": {"product_type": ("text", 60), "size": ("text", 30), "colour": ("text", 40), "material": ("text", 80),
                         "fit": ("text", 40), "care_instructions": ("text", 300)},
    "Makeup, Beauty & Skincare": {"product_type": ("text", 60), "net_quantity": ("text", 40), "ingredients": ("text", 1000),
                                  "directions": ("text", 500), "warnings": ("text", 500), "batch_no": ("text", 40),
                                  "expiry_date": ("date", 10), "manufacturer": ("text", 120), "country_of_origin": ("text", 60)},
    "Household Essentials": {"material": ("text", 80), "dimensions": ("text", 60), "weight_g": ("number", 100000),
                             "usage_instructions": ("text", 500), "safety_info": ("text", 500)},
}
VARIANT_ATTRIBUTES = {"size", "colour", "design", "fabric", "pack_size", "weight", "quantity", "shade"}
SKU_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{1,39}")
DOC_TYPES = {"license", "test_report", "invoice", "authenticity", "certificate", "other"}


def validate_attributes(category: str, attrs: Optional[dict]) -> dict:
    spec = ATTRIBUTE_SPECS.get(category)
    if spec is None:
        raise ValueError("Unknown category.")
    out = {}
    for k, v in (attrs or {}).items():
        if k not in spec:
            raise ValueError(f"'{k}' is not a field for {category}.")
        kind, limit = spec[k]
        if v is None or v == "":
            continue
        if kind == "text":
            if not isinstance(v, str) or len(v.strip()) > limit:
                raise ValueError(f"'{k}' must be text up to {limit} characters.")
            out[k] = v.strip()
        elif kind == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= limit):
                raise ValueError(f"'{k}' must be a number between 0 and {limit}.")
            out[k] = v
        else:  # date
            try:
                date.fromisoformat(str(v))
            except ValueError:
                raise ValueError(f"'{k}' must be a date like 2027-03-31.")
            out[k] = str(v)
    return out


def validate_package(pkg: Optional[dict]) -> dict:
    pkg = pkg or {}
    out = {}
    for k, hi in (("weight_g", 100000), ("length_cm", 500), ("width_cm", 500), ("height_cm", 500)):
        if pkg.get(k) not in (None, ""):
            v = pkg[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= hi):
                raise ValueError(f"package.{k} must be a number between 0 and {hi}.")
            out[k] = v
    if pkg.get("handling_days") not in (None, ""):
        v = pkg["handling_days"]
        if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v <= 30):
            raise ValueError("package.handling_days must be a whole number of days (0-30).")
        out["handling_days"] = v
    if "fragile" in pkg:
        out["fragile"] = bool(pkg["fragile"])
    return out


def validate_variants(variants: Optional[list], product_sku: str, existing: Optional[list] = None) -> list:
    """Each purchasable variant has its own SKU, optional price override and its own stock. Stock of EXISTING variants is
    never taken from the payload (it changes only through reason-based adjustments); new variants take their initial stock."""
    out, seen = [], set()
    have = {v["sku"]: v for v in (existing or [])}
    for v in variants or []:
        sku = str(v.get("sku", "")).strip().upper()
        if not SKU_RE.fullmatch(sku):
            raise ValueError("Each variant needs a SKU (2-40 letters, numbers, . _ -).")
        if sku in seen or sku == product_sku.upper():
            raise ValueError(f"Duplicate SKU '{sku}'.")
        seen.add(sku)
        attrs = {k: str(x).strip()[:60] for k, x in (v.get("attributes") or {}).items() if str(x).strip()}
        bad = set(attrs) - VARIANT_ATTRIBUTES
        if bad:
            raise ValueError(f"Variant attribute '{sorted(bad)[0]}' is not supported (use {', '.join(sorted(VARIANT_ATTRIBUTES))}).")
        if not attrs:
            raise ValueError(f"Variant '{sku}' needs at least one attribute (e.g. size or colour).")
        row = {"sku": sku, "attributes": attrs}
        for pk in ("price", "mrp"):
            if v.get(pk) not in (None, ""):
                if isinstance(v[pk], bool) or not isinstance(v[pk], (int, float)) or v[pk] <= 0:
                    raise ValueError(f"Variant '{sku}' {pk} must be greater than 0.")
                row[pk] = v[pk]
        if row.get("price") and row.get("mrp") and row["price"] > row["mrp"]:
            raise ValueError(f"Variant '{sku}': price cannot be higher than MRP.")
        if sku in have:
            row["stock"] = have[sku]["stock"]
        else:
            st = v.get("stock", 0)
            if isinstance(st, bool) or not isinstance(st, int) or st < 0 or st > 1_000_000:
                raise ValueError(f"Variant '{sku}' stock must be a whole number of 0 or more.")
            row["stock"] = st
        out.append(row)
    removed = [s for s in have if s not in seen and have[s]["stock"] > 0]
    if removed:
        raise ValueError(f"Variant '{removed[0]}' still has stock; reduce it to 0 (with a reason) before removing it.")
    return out


def validate_documents(docs: Optional[list]) -> list:
    out = []
    for d in docs or []:
        if d.get("type") not in DOC_TYPES:
            raise ValueError(f"Document type must be one of {', '.join(sorted(DOC_TYPES))}.")
        url = safe_image_refs([d.get("url", "")], 1)[0]
        out.append({"type": d["type"], "url": url, "note": str(d.get("note", ""))[:200], "status": "submitted"})   # never 'verified' from a vendor
    if len(out) > 10:
        raise ValueError("At most 10 documents per product.")
    return out


# ---------------------------------------------------------------- CSV
CSV_COLUMNS = ["sku", "name", "name_hi", "category", "subcategory", "brand", "description", "mrp", "selling_price", "gst_percent",
               "stock", "low_stock_threshold", "images", "weight_g", "return_policy"]
STOCK_COLUMNS = ["sku", "variant_sku", "delta", "reason"]


def csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def products_to_csv(products: List[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS + ["approval_status", "is_active", "archived", "updated_at"])
    for p in products:
        w.writerow([csv_safe(p.get("sku")), csv_safe(p.get("name")), csv_safe(p.get("name_hi", "")), p.get("category", ""),
                    csv_safe(p.get("subcategory", "")), csv_safe(p.get("brand", "")), csv_safe(p.get("description", "")),
                    p.get("mrp"), p.get("selling_price"), p.get("gst_percent"), p.get("stock"), p.get("low_stock_threshold", ""),
                    "|".join(p.get("images") or []), (p.get("package") or {}).get("weight_g", ""), csv_safe(p.get("return_policy", "")),
                    p.get("approval_status"), p.get("is_active"), bool(p.get("archived")), p.get("updated_at", "")])
    return buf.getvalue()


def template_csv(kind: str = "products") -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "stock":
        w.writerow(STOCK_COLUMNS)
        w.writerow(["SAREE-001", "", "10", "Received new batch"])
    else:
        w.writerow(CSV_COLUMNS)
        w.writerow(["SAREE-001", "Banarasi Silk Saree", "", "Sarees", "Silk", "House Brand", "Hand-woven silk saree", "4500", "2999", "5",
                    "25", "5", "/brand/pillar-sarees.jpg", "700", "7 days return"])
    return buf.getvalue()


def parse_csv(text: str, required: List[str], max_rows: int = 500) -> List[dict]:
    if len(text) > 1_000_000:
        raise ValueError("The file is too large (max 1 MB).")
    rdr = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = [c.strip() for c in (rdr.fieldnames or [])]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(missing)}.")
    rows = []
    for i, row in enumerate(rdr, start=2):
        if i - 1 > max_rows:
            raise ValueError(f"At most {max_rows} rows per file.")
        rows.append({"_row": i, **{(k or "").strip(): (v or "").strip() for k, v in row.items()}})
    if not rows:
        raise ValueError("The file has no data rows.")
    return rows
