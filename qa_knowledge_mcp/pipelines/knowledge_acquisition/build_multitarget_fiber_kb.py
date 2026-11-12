from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from .paths import project_path


SOURCES = [
    {
        "key": "10.1086/324741",
        "title": "Sloan Digital Sky Survey: Early Data Release",
        "year": 2002,
        "category": "经典巡天数据处理",
        "url": "https://skyserver.sdss.org/dr4/sp/sdss/edrpaper/edrpaper.pdf",
    },
    {
        "key": "10.3847/1538-3881/acb212",
        "title": "The Spectroscopic Data Processing Pipeline for the Dark Energy Spectroscopic Instrument",
        "year": 2023,
        "category": "现代巡天数据处理",
        "url": "https://www.pure.ed.ac.uk/ws/portalfiles/portal/321765839/paper.pdf",
    },
    {
        "key": "10.1117/12.2561194",
        "title": "Prime Focus Spectrograph (PFS): the prime focus instrument",
        "year": 2020,
        "category": "PFS仪器与数据链路",
        "url": "https://doi.org/10.1117/12.2561194",
    },
    {
        "key": "arXiv:1505.01570",
        "title": "The first data release (DR1) of the LAMOST regular survey",
        "year": 2015,
        "category": "LAMOST数据处理与发布",
        "url": "https://arxiv.org/pdf/1505.01570",
    },
    {
        "key": "arXiv:1507.00725",
        "title": "Prime Focus Spectrograph for the Subaru telescope: massively multiplexed optical and near-infrared fiber spectrograph",
        "year": 2015,
        "category": "PFS仪器与数据链路",
        "url": "https://arxiv.org/pdf/1507.00725",
    },
    {
        "key": "10.21105/joss.02308",
        "title": "PypeIt: The Python Spectroscopic Data Reduction Pipeline",
        "year": 2020,
        "category": "通用光谱数据处理",
        "url": "https://arxiv.org/pdf/2005.06505",
    },
    {
        "key": "arXiv:2503.14738",
        "title": "Data Release 1 of the Dark Energy Spectroscopic Instrument",
        "year": 2025,
        "category": "DESI近年数据发布",
        "url": "https://arxiv.org/pdf/2503.14738",
    },
    {"key": "10.17863/cam.20755", "title": "The thirteenth data release of the Sloan Digital Sky Survey", "year": 2016, "category": "SDSS数据发布", "local": "10.17863_cam.20755.md"},
    {"key": "10.1088/0004-6256/145/1/10", "title": "The Baryon Oscillation Spectroscopic Survey of SDSS-III", "year": 2013, "category": "SDSS/BOSS巡天管线", "local": "10.1088_0004-6256_145_1_10.md"},
    {"key": "10.1051/0004-6361/201220142", "title": "The Sloan Digital Sky Survey quasar catalog: ninth data release", "year": 2013, "category": "SDSS数据产品", "local": "10.1051_0004-6361_201220142.md"},
    {"key": "10.1093/mnras/staa3336", "title": "The completed SDSS-IV extended Baryon Oscillation Spectroscopic Survey: large-scale structure catalogues", "year": 2020, "category": "SDSS/eBOSS数据产品", "local": "10.1093_mnras_staa3336.md"},
    {"key": "10.1093/mnras/stab510", "title": "The completed SDSS-IV extended Baryon Oscillation Spectroscopic Survey: 1000 multi-tracer mock catalogues", "year": 2021, "category": "巡天模拟与系统误差", "local": "10.1093_mnras_stab510.md"},
    {"key": "10.1093/mnras/stv2826", "title": "BOSS mock galaxy catalogues for the final data release", "year": 2015, "category": "巡天模拟与系统误差", "local": "10.1093_mnras_stv2826.md"},
    {"key": "10.1093/mnras/stu523", "title": "Baryon acoustic oscillations in the SDSS-III BOSS Data Releases 10 and 11", "year": 2014, "category": "SDSS/BOSS科学数据处理", "local": "10.1093_mnras_stu523.md"},
    {"key": "10.1093/mnras/stu2465", "title": "BOSS mock galaxy catalogues for the low-redshift sample", "year": 2014, "category": "巡天模拟与系统误差", "local": "10.1093_mnras_stu2465.md"},
    {"key": "10.1088/1475-7516/2017/04/008", "title": "Imprint of DESI fiber assignment on the anisotropic power spectrum", "year": 2017, "category": "DESI光纤分配与系统误差", "local": "10.1088_1475-7516_2017_04_008.md"},
    {"key": "10.3847/1538-3881/ad45fe", "title": "The Optical Corrector for the Dark Energy Spectroscopic Instrument", "year": 2024, "category": "DESI仪器与标定", "local": "10.3847_1538-3881_ad45fe.md"},
    {"key": "10.1093/mnras/stae1610", "title": "Broad absorption line quasars in the DESI Early Data Release", "year": 2024, "category": "DESI早期数据产品", "local": "10.1093_mnras_stae1610.md"},
    {"key": "10.1093/mnras/stad3559", "title": "The DESI One-Percent Survey", "year": 2023, "category": "DESI巡天数据产品", "local": "10.1093_mnras_stad3559.md"},
    {"key": "10.1093/mnras/stae2290", "title": "The DESI Y1 spectroscopic survey and large-scale tidal field", "year": 2024, "category": "DESI巡天数据产品", "local": "10.1093_mnras_stae2290.md"},
    {"key": "10.1088/1475-7516/2025/01/134", "title": "Effective field theory models for DESI 2024 and future surveys", "year": 2025, "category": "DESI近年分析管线", "local": "10.1088_1475-7516_2025_01_134.md"},
    {"key": "10.1088/1475-7516/2025/11/077", "title": "Joint analysis of 3D clustering and CMB lensing with DESI DR1 galaxies", "year": 2025, "category": "DESI近年数据分析", "local": "10.1088_1475-7516_2025_11_077.md"},
    {"key": "10.1088/1475-7516/2026/06/043", "title": "Cosmological constraints from joint DESI DR1 Full-Shape and DR2 BAO", "year": 2026, "category": "DESI近年数据分析", "local": "10.1088_1475-7516_2026_06_043.md"},
    {"key": "10.1088/1475-7516/2025/06/029", "title": "Primordial non-Gaussianity with DESI 2024 LRG and QSO samples", "year": 2025, "category": "DESI近年数据分析", "local": "10.1088_1475-7516_2025_06_029.md"},
    {"key": "10.1088/1475-7516/2025/01/136", "title": "Compressed and Full-Modeling analyses with FOLPS for DESI", "year": 2025, "category": "DESI近年分析管线", "local": "10.1088_1475-7516_2025_01_136.md"},
    {"key": "10.1088/1475-7516/2025/01/138", "title": "Parameter compression and Full-Modeling with Velocileptors for DESI", "year": 2025, "category": "DESI近年分析管线", "local": "10.1088_1475-7516_2025_01_138.md"},
    {"key": "10.1088/1475-7516/2025/01/143", "title": "Suppressing sample variance of DESI-like galaxy clustering with fast simulations", "year": 2025, "category": "DESI近年模拟与系统误差", "local": "10.1088_1475-7516_2025_01_143.md"},
    {"key": "10.1088/1475-7516/2025/05/040", "title": "DESI forecast for dark matter-neutrino interactions using EFTofLSS", "year": 2025, "category": "DESI近年分析管线", "local": "10.1088_1475-7516_2025_05_040.md"},
    {"key": "10.1088/1475-7516/2025/05/099", "title": "Emulating the Lyman-alpha forest 1D power spectrum", "year": 2025, "category": "DESI近年分析管线", "local": "10.1088_1475-7516_2025_05_099.md"},
    {"key": "10.1093/mnras/stae1792", "title": "Redshift evolution and covariances for DESI Y1 lensing and clustering", "year": 2024, "category": "DESI巡天数据分析", "local": "10.1093_mnras_stae1792.md"},
]


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.replace("/", "_"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the multi-target fiber spectroscopy paper manifest and local text sources.")
    parser.add_argument("--root", type=Path, default=Path("data/knowledge_bases/multitarget_fiber_spectroscopy"))
    parser.add_argument("--processed-papers-root", type=Path,
                        default=os.environ.get("QA_PROCESSED_PAPERS_ROOT") or Path("data/knowledge_acquisition/processed_papers"))
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    root = project_path(args.root)
    processed_root = project_path(args.processed_papers_root)
    pdf_root = root / "pdf"
    text_root = root / "papers"
    pdf_root.mkdir(parents=True, exist_ok=True)
    text_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rank, item in enumerate(SOURCES, start=1):
        stem = safe_name(item["key"])
        pdf_path = pdf_root / f"{stem}.pdf"
        text_path = text_root / f"{stem}.md"
        status = "ready"
        error = None
        local_source = processed_root / item["local"] if item.get("local") else None
        if local_source and local_source.exists():
            text_path.parent.mkdir(parents=True, exist_ok=True)
            if not text_path.exists():
                text_path.write_text(local_source.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        elif not args.skip_download and not pdf_path.exists():
            try:
                request = urllib.request.Request(item["url"], headers={"User-Agent": "multitarget-fiber-kb/1.0"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    pdf_path.write_bytes(response.read())
            except Exception as exc:  # noqa: BLE001
                status, error = "download_failed", f"{type(exc).__name__}: {exc}"
        if pdf_path.exists() and not text_path.exists():
            try:
                subprocess.run(["pdftotext", "-layout", str(pdf_path), str(text_path)], check=True, capture_output=True)
            except Exception as exc:  # noqa: BLE001
                status, error = "text_extract_failed", f"{type(exc).__name__}: {exc}"
        if not text_path.exists():
            status = "source_missing" if status == "ready" else status
        manifest.append({
            "rank": rank,
            "key": item["key"],
            "title": item["title"],
            "year": item["year"],
            "category": item["category"],
            "source": str(text_path.relative_to(root.parent.parent.parent)),
            "source_url": item.get("url") or item.get("local"),
            "status": status,
            **({"error": error} if error else {}),
        })
    (root / "papers.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"root": str(root), "papers": len(manifest), "ready": sum(row["status"] == "ready" for row in manifest), "missing": [row["key"] for row in manifest if row["status"] != "ready"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
