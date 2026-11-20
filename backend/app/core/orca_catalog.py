"""Extractor e indexador del Catálogo Universal de Impresoras basado en OrcaSlicer."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from app.config import PROFILES_DIR

BUNDLED_ORCA_CATALOG_PATH = PROFILES_DIR / "orca_printers_catalog.json"
ORCA_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles"

DEFAULT_SYNC_VENDORS: tuple[str, ...] = (
    "BBL",
    "Creality",
    "Prusa",
    "Anycubic",
    "Elegoo",
    "Voron",
    "Qidi",
    "Flashforge",
    "FLSun",
    "Sovol",
    "Artillery",
    "Ratrig",
    "Anker",
    "BIQU",
    "Snapmaker",
    "Raise3D",
    "Kingroon",
    "TwoTrees",
    "Geeetech",
    "Tronxy",
    "Voxelab",
    "Vzbot",
    "UltiMaker",
    "Comgrow",
    "LONGER",
)

_CATALOG_CACHE: dict[str, dict[str, Any]] | None = None


def _parse_printable_area(area_list: Any) -> tuple[str, float, float, float | None]:
    if not isinstance(area_list, list) or len(area_list) < 4:
        return ("rectangular", 220.0, 220.0, None)
    pts: list[tuple[float, float]] = []
    for item in area_list:
        if isinstance(item, str) and "x" in item:
            try:
                x_str, y_str = item.split("x", 1)
                pts.append((float(x_str), float(y_str)))
            except Exception:
                continue
    if len(pts) < 4:
        return ("rectangular", 220.0, 220.0, None)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = round(max(xs) - min(xs), 1)
    d = round(max(ys) - min(ys), 1)
    if len(pts) > 8 and abs(w - d) <= 4.0 and min(xs) < 0 and min(ys) < 0:
        return ("circular", w, d, round((w + d) / 2.0, 1))
    return ("rectangular", w, d, None)


def _first_num(val: Any, default: float = 0.0) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, list) and val:
        val = val[0]
    if isinstance(val, str):
        m = re.search(r"[-+]?\d+(?:\.\d+)?", val)
        if m:
            return float(m.group(0))
    return default


def _normalize_flavor(raw: Any) -> str:
    s = str(raw or "").lower()
    if "klipper" in s:
        return "klipper"
    if "bambu" in s:
        return "bambu"
    if "reprap" in s:
        return "reprap"
    return "marlin2"


def _infer_kinematics_and_qmax(
    vendor_key: str,
    model_name: str,
    bed_shape: str,
    flavor: str,
    max_acc: int,
    props_blob: str,
) -> tuple[str, bool, float]:
    if bed_shape == "circular":
        kin = "delta"
    elif (
        max_acc >= 8000
        or vendor_key in ("BBL", "Voron", "Ratrig", "Vzbot")
        or (
            vendor_key in ("Qidi", "Flashforge", "Creality")
            and ("corexy" in props_blob or max_acc >= 5000 or "k1" in model_name.lower() or "k2" in model_name.lower())
        )
    ):
        kin = "corexy"
    else:
        kin = "cartesian"

    is_hs = (max_acc >= 8000) or (flavor == "klipper" and max_acc >= 5000) or (flavor == "bambu")
    if is_hs and max_acc >= 12000:
        q_max = 26.0
    elif is_hs:
        q_max = 20.0
    elif kin == "corexy":
        q_max = 18.0
    else:
        q_max = 12.0
    return kin, is_hs, q_max


def _extract_machine_entry(
    vendor_key: str,
    vendor_name: str,
    model_name: str,
    mod_data: dict[str, Any],
    props: dict[str, Any],
    rep_sub_path: str,
) -> dict[str, Any]:
    raw_nozzles = str(mod_data.get("nozzle_diameter") or "0.4")
    nozzles = sorted(
        {
            round(float(x), 2)
            for x in re.findall(r"\d+(?:\.\d+)?", raw_nozzles)
            if 0.1 <= float(x) <= 1.2
        }
    ) or [0.4]

    bed_shape, bw, bd, bdiam = _parse_printable_area(props.get("printable_area"))
    max_h = round(_first_num(props.get("printable_height"), 250.0), 1)
    flavor = _normalize_flavor(props.get("gcode_flavor"))
    max_spd = int(round(_first_num(props.get("machine_max_speed_x"), 200.0)))
    max_acc = int(round(_first_num(props.get("machine_max_acceleration_x"), 3000.0)))
    kin, is_hs, q_max = _infer_kinematics_and_qmax(
        vendor_key, model_name, bed_shape, flavor, max_acc, str(props).lower()
    )

    semm = str(props.get("single_extruder_multi_material", "0")) == "1"
    nz_list = props.get("nozzle_diameter")
    multi_ext = isinstance(nz_list, list) and len(nz_list) > 1
    lower_m = model_name.lower()
    known_mc = (vendor_key == "BBL") or any(
        k in lower_m
        for k in (
            "cfs",
            "ace",
            "mmu",
            "ad5x",
            "creator 5",
            "kobra 3",
            "kobra s1",
            "hi combo",
            "toolchanger",
            "xl",
            "idex",
        )
    )
    is_mc = semm or multi_ext or known_mc
    tool_cnt = len(nz_list) if multi_ext else (4 if is_mc else 1)
    if "xl" in lower_m and "prusa" in vendor_name.lower():
        tool_cnt = 5

    chamber_t = _first_num(props.get("chamber_temperature"), 0.0)
    has_chamber = (
        chamber_t > 0
        or str(props.get("support_chamber_temp_control", "0")) == "1"
        or any(
            k in lower_m
            for k in (
                "x1c",
                "x1e",
                "x1 ",
                "p1s",
                "h2d",
                "k1",
                "k2",
                "q1",
                "x-max",
                "x-plus",
                "plus4",
                "creator",
                "adventurer 5m pro",
                "voron 2.4",
                "trident",
            )
        )
    )

    slug = re.sub(r"[^a-z0-9]+", "_", f"{vendor_key}_{model_name}".lower()).strip("_")
    return {
        "catalog_id": slug,
        "vendor": vendor_name,
        "vendor_key": vendor_key,
        "model_name": model_name,
        "nozzle_diameters": nozzles,
        "profile_sub_path": rep_sub_path,
        "bed_shape": bed_shape,
        "bed_width_mm": bw,
        "bed_depth_mm": bd,
        "bed_diameter_mm": bdiam,
        "max_height_mm": max_h,
        "kinematics": kin,
        "gcode_flavor": flavor,
        "max_speed_mm_s": max_spd,
        "max_accel_mm_s2": max_acc,
        "estimated_q_max": q_max,
        "capabilities": {
            "is_multicolor": is_mc,
            "tool_count": tool_cnt,
            "has_heated_chamber": has_chamber,
            "is_high_speed": is_hs,
        },
    }


def _find_local_orca_profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    if sys.platform == "darwin":
        dirs.extend(
            [
                Path("/Applications/OrcaSlicer.app/Contents/Resources/profiles"),
                Path.home() / "Applications/OrcaSlicer.app/Contents/Resources/profiles",
                Path.home() / "Library/Application Support/OrcaSlicer/system",
            ]
        )
    elif sys.platform.startswith("win"):
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        dirs.extend(
            [
                pf / "OrcaSlicer" / "resources" / "profiles",
                appdata / "OrcaSlicer" / "system",
            ]
        )
    else:
        dirs.extend(
            [
                Path("/usr/share/OrcaSlicer/resources/profiles"),
                Path.home() / ".config/OrcaSlicer/system",
            ]
        )

    try:
        from app.core.platform_detector import get_detected_slicer_executable

        exe = get_detected_slicer_executable("orcaslicer")
        if exe is not None:
            for parent in exe.parents:
                cand = parent / "Resources" / "profiles"
                if cand.is_dir():
                    dirs.append(cand)
                cand2 = parent / "resources" / "profiles"
                if cand2.is_dir():
                    dirs.append(cand2)
    except Exception:
        pass

    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        if d.is_dir() and str(d) not in seen:
            seen.add(str(d))
            unique.append(d)
    return unique


def _scan_local_orca_profiles() -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for prof_dir in _find_local_orca_profile_dirs():
        for vendor_json in prof_dir.glob("*.json"):
            if vendor_json.name in ("blacklist.json", "OrcaFilamentLibrary.json"):
                continue
            try:
                vj = json.loads(vendor_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(vj, dict) or not vj.get("machine_model_list"):
                continue
            vendor_key = vendor_json.stem
            vendor_name = str(vj.get("name") or vendor_key)
            vendor_dir = prof_dir / vendor_key
            if not vendor_dir.is_dir():
                continue
            sub_by_name = {
                m.get("name"): m.get("sub_path")
                for m in vj.get("machine_list", [])
                if isinstance(m, dict) and m.get("name") and m.get("sub_path")
            }

            def _load_sub(sub_path: str) -> dict[str, Any]:
                p = vendor_dir / sub_path
                if not p.is_file():
                    return {}
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    return {}

            def _resolve(sub_path: str, depth: int = 0) -> dict[str, Any]:
                if not sub_path or depth > 6:
                    return {}
                data = _load_sub(sub_path)
                inh = data.get("inherits")
                if inh and inh in sub_by_name:
                    merged = _resolve(str(sub_by_name[inh]), depth + 1)
                    merged.update(data)
                    return merged
                return data

            for mod in vj.get("machine_model_list", []):
                if not isinstance(mod, dict):
                    continue
                mname = str(mod.get("name") or "").strip()
                if not mname or "template" in mname.lower():
                    continue
                mod_sub = str(mod.get("sub_path") or "")
                mod_data = _load_sub(mod_sub)
                rep_sub = None
                for cand in (f"{mname} 0.4 nozzle", f"{mname} 0.4", mname):
                    if cand in sub_by_name:
                        rep_sub = str(sub_by_name[cand])
                        break
                if not rep_sub:
                    for k, sp in sub_by_name.items():
                        if str(k).startswith(mname) and "template" not in str(k).lower():
                            rep_sub = str(sp)
                            break
                props = _resolve(rep_sub) if rep_sub else mod_data
                entry = _extract_machine_entry(
                    vendor_key,
                    vendor_name,
                    mname,
                    mod_data,
                    props,
                    f"{vendor_key}/{rep_sub or mod_sub}",
                )
                items[entry["catalog_id"]] = entry
    return items


def load_orca_catalog(force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Carga el catálogo unificado (índice JSON integrado + perfiles locales de OrcaSlicer)."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None and not force_reload:
        return _CATALOG_CACHE

    catalog: dict[str, dict[str, Any]] = {}
    if BUNDLED_ORCA_CATALOG_PATH.is_file():
        try:
            raw = json.loads(BUNDLED_ORCA_CATALOG_PATH.read_text(encoding="utf-8"))
            for item in raw.get("printers", []):
                if isinstance(item, dict) and item.get("catalog_id"):
                    catalog[str(item["catalog_id"])] = item
        except Exception:
            pass

    local_items = _scan_local_orca_profiles()
    catalog.update(local_items)
    _CATALOG_CACHE = catalog
    return catalog


def get_orca_catalog_entry(catalog_id: str) -> dict[str, Any] | None:
    return load_orca_catalog().get(catalog_id)


def list_catalog_vendors() -> list[str]:
    cat = load_orca_catalog()
    return sorted({str(item.get("vendor") or "") for item in cat.values() if item.get("vendor")})


def search_orca_catalog(
    q: str = "",
    vendor: str = "",
    multicolor_only: bool = False,
    limit: int = 120,
) -> dict[str, Any]:
    """Busca impresoras en el catálogo OrcaSlicer por marca, modelo o capacidades."""
    cat = load_orca_catalog()
    q_norm = q.strip().lower()
    v_norm = vendor.strip().lower()

    results: list[dict[str, Any]] = []
    for item in cat.values():
        if v_norm and str(item.get("vendor") or "").lower() != v_norm:
            continue
        caps = item.get("capabilities") or {}
        if multicolor_only and not caps.get("is_multicolor", False):
            continue
        if q_norm:
            haystack = " ".join(
                [
                    str(item.get("vendor") or ""),
                    str(item.get("model_name") or ""),
                    str(item.get("gcode_flavor") or ""),
                    str(item.get("kinematics") or ""),
                    "multicolor ams cfs" if caps.get("is_multicolor") else "monocolor",
                ]
            ).lower()
            if not all(tok in haystack for tok in q_norm.split()):
                continue
        results.append(item)

    results.sort(key=lambda x: (str(x.get("vendor") or "").lower(), str(x.get("model_name") or "").lower()))
    return {
        "printers": results[: max(1, min(limit, 500))],
        "total": len(results),
        "catalog_total": len(cat),
        "vendors": list_catalog_vendors(),
    }


def sync_orca_catalog_from_github(vendors: tuple[str, ...] = DEFAULT_SYNC_VENDORS) -> dict[str, Any]:
    """Sincroniza el catálogo directamente desde `OrcaSlicer/OrcaSlicer` en GitHub."""
    def _fetch_vendor(v: str) -> list[dict[str, Any]]:
        client = httpx.Client(timeout=15.0)
        r = client.get(f"{ORCA_GITHUB_RAW_BASE}/{v}.json")
        if r.status_code != 200:
            return []
        vj = r.json()
        vname = str(vj.get("name") or v)
        sub_by_name = {
            m.get("name"): m.get("sub_path")
            for m in vj.get("machine_list", [])
            if isinstance(m, dict) and m.get("name") and m.get("sub_path")
        }
        cache: dict[str, dict[str, Any]] = {}

        def _get_m(sp: str) -> dict[str, Any]:
            if not sp:
                return {}
            if sp not in cache:
                try:
                    resp = client.get(f"{ORCA_GITHUB_RAW_BASE}/{v}/{sp}")
                    cache[sp] = resp.json() if resp.status_code == 200 else {}
                except Exception:
                    cache[sp] = {}
            return cache[sp]

        def _resolve(sp: str, depth: int = 0) -> dict[str, Any]:
            if not sp or depth > 6:
                return {}
            data = dict(_get_m(sp))
            inh = data.get("inherits")
            if inh and inh in sub_by_name:
                merged = _resolve(str(sub_by_name[inh]), depth + 1)
                merged.update(data)
                return merged
            return data

        out: list[dict[str, Any]] = []
        for mod in vj.get("machine_model_list", []):
            if not isinstance(mod, dict):
                continue
            mname = str(mod.get("name") or "").strip()
            if not mname or "template" in mname.lower():
                continue
            mod_sub = str(mod.get("sub_path") or "")
            mod_data = _get_m(mod_sub)
            rep_sub = None
            for cand in (f"{mname} 0.4 nozzle", f"{mname} 0.4", mname):
                if cand in sub_by_name:
                    rep_sub = str(sub_by_name[cand])
                    break
            if not rep_sub:
                for k, sp in sub_by_name.items():
                    if str(k).startswith(mname) and "template" not in str(k).lower():
                        rep_sub = str(sp)
                        break
            props = _resolve(rep_sub) if rep_sub else mod_data
            out.append(
                _extract_machine_entry(
                    v, vname, mname, mod_data, props, f"{v}/{rep_sub or mod_sub}"
                )
            )
        return out

    all_items: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(_fetch_vendor, vendors):
            all_items.extend(res)

    if all_items:
        BUNDLED_ORCA_CATALOG_PATH.write_text(
            json.dumps(
                {"source": "OrcaSlicer/OrcaSlicer", "count": len(all_items), "printers": all_items},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        load_orca_catalog(force_reload=True)
    return {"synced_count": len(all_items), "vendors": len({i["vendor"] for i in all_items})}
