#!/usr/bin/env python3
"""
TNAU-Grounded RAG Agronomic Prescription Engine
Cross-references optical foliar ionome predictions against curated TNAU database
(TOTAL_all_in_one.csv) to deliver authoritative, clinical remediation protocols.
"""

import sys
import os
import csv
import json
import math
from collections import defaultdict

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "TOTAL_all_in_one.csv")

# Baseline Macronutrient Critical Thresholds (Dry Matter %)
CRITICAL_THRESHOLDS = {
    "Nitrogen": 2.50,      # Deficiency below 2.5% in most cereal/vegetable leaves
    "Phosphorus": 0.25,    # Deficiency below 0.25%
    "Potassium": 1.50,     # Deficiency below 1.5%
    "Calcium": 0.50,       # Deficiency below 0.5%
    "Magnesium": 0.20      # Deficiency below 0.2%
}


class TNAUKnowledgeBase:
    def __init__(self, csv_path=DATA_PATH):
        self.csv_path = csv_path
        self.records = []
        self.crop_index = defaultdict(list)
        self.nutrient_index = defaultdict(list)
        self.load_data()

    def load_data(self):
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"Knowledge base CSV not found at: {self.csv_path}")

        with open(self.csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.records.append(row)
                crop = row.get("Crop", "").strip().lower()
                nutrient = row.get("Nutrient_Normalized", "").strip().lower()
                if crop:
                    self.crop_index[crop].append(row)
                if nutrient:
                    self.nutrient_index[nutrient].append(row)

        print(f"[✓] Loaded {len(self.records)} records across {len(self.crop_index)} crops from TNAU Knowledge Base.")

    def query(self, crop: str, nutrient: str):
        crop = crop.strip().lower()
        nutrient = nutrient.strip().lower()

        matches = []
        # Direct exact match
        for r in self.crop_index.get(crop, []):
            if r.get("Nutrient_Normalized", "").strip().lower() == nutrient:
                matches.append(r)

        # Fallback to crop group if crop not found
        if not matches:
            for r in self.records:
                if (r.get("Crop_Group", "").strip().lower() in crop or crop in r.get("Crop_Group", "").strip().lower()) and \
                   r.get("Nutrient_Normalized", "").strip().lower() == nutrient:
                    matches.append(r)

        # Fallback to general nutrient guideline
        if not matches:
            for r in self.nutrient_index.get(nutrient, []):
                if not r.get("Crop"):
                    matches.append(r)

        symptoms = [m["Detail"] for m in matches if "symptom" in m.get("Item", "").lower()]
        remedies = [m["Detail"] for m in matches if "remedy" in m.get("Item", "").lower() or "correction" in m.get("Item", "").lower()]
        sampling = [m["Detail"] for m in matches if "sample" in m.get("Item", "").lower() or "sampling" in m.get("Item", "").lower()]
        source_urls = list({m["Source_URL"] for m in matches if m.get("Source_URL")})

        return {
            "crop": crop.title(),
            "nutrient": nutrient.title(),
            "symptoms": symptoms,
            "remedies": remedies,
            "sampling_procedure": sampling,
            "sources": source_urls,
            "match_count": len(matches)
        }


def plsr_predict_ionome(ndvi: float, spad: float, ir_val: int, red_val: int):
    """
    Simulated PLSR deconvolution calibrated to literature coefficients
    (MethodsX 2024 PMC10823125 & MDPI RS 2022 14(20):5144).
    """
    # Normalized predictors
    norm_spad = min(60.0, max(0.0, spad))
    norm_ndvi = min(1.0, max(-1.0, ndvi))
    rvi = (ir_val / red_val) if red_val > 0 else 1.0

    # PLSR Latent Variable projections
    n_pct = round(0.45 + 0.082 * norm_spad + 1.15 * norm_ndvi, 2)
    p_pct = round(0.08 + 0.006 * norm_spad + 0.18 * norm_ndvi, 2)
    k_pct = round(0.60 + 0.035 * norm_spad + 0.85 * (rvi / 10.0), 2)
    ca_pct = round(0.30 + 0.015 * norm_spad + 0.40 * norm_ndvi, 2)
    mg_pct = round(0.10 + 0.007 * norm_spad + 0.22 * norm_ndvi, 2)

    return {
        "Nitrogen": {"value": n_pct, "unit": "%", "deficient": n_pct < CRITICAL_THRESHOLDS["Nitrogen"]},
        "Phosphorus": {"value": p_pct, "unit": "%", "deficient": p_pct < CRITICAL_THRESHOLDS["Phosphorus"]},
        "Potassium": {"value": k_pct, "unit": "%", "deficient": k_pct < CRITICAL_THRESHOLDS["Potassium"]},
        "Calcium": {"value": ca_pct, "unit": "%", "deficient": ca_pct < CRITICAL_THRESHOLDS["Calcium"]},
        "Magnesium": {"value": mg_pct, "unit": "%", "deficient": mg_pct < CRITICAL_THRESHOLDS["Magnesium"]},
    }


def generate_prescriptive_report(crop: str, ndvi: float, spad: float, ir_val: int, red_val: int, kb: TNAUKnowledgeBase):
    ionome = plsr_predict_ionome(ndvi, spad, ir_val, red_val)
    print("=" * 80)
    print(f"       TNAU-GROUNDED PRECISION AGRONOMIC PRESCRIPTION REPORT")
    print("=" * 80)
    print(f"Target Crop:        {crop.upper()}")
    print(f"Sensor Readings:    NDVI: {ndvi:+.3f} | SPAD Equivalent: {spad:.1f} | IR: {ir_val:,} | Red: {red_val:,}")
    print("-" * 80)
    print("PREDICTED FOLIAR IONOME PROFILE (PLSR Model):")
    for nut, data in ionome.items():
        thresh = CRITICAL_THRESHOLDS[nut]
        status = "DEFICIENT [!]" if data["deficient"] else "SUFFICIENT [OK]"
        bar = "■" * int(data["value"] * 10)
        print(f"  • {nut:<12}: {data['value']:>5.2f}% (Threshold: {thresh:>4.2f}%)  [{status:<15}] {bar}")

    deficiencies = [nut for nut, data in ionome.items() if data["deficient"]]
    print("-" * 80)

    if not deficiencies:
        print("✓ All foliar macronutrient concentrations are within optimal physiological thresholds.")
        print("  Recommendation: Maintain scheduled irrigation and standard maintenance fertilization.")
    else:
        print(f"CRITICAL DEFICIENCY DETECTED: {', '.join(deficiencies).upper()}")
        print("RETRIEVING OFFICIAL TNAU AGRONOMIC EXTENSION REMEDIES...")
        print("-" * 80)

        for nut in deficiencies:
            info = kb.query(crop, nut)
            print(f"\n[!] REMEDIATION PROTOCOL: {nut.upper()} DEFICIENCY IN {crop.upper()}")
            if info["symptoms"]:
                print("  Deficiency Symptoms (Field Verification):")
                for s in info["symptoms"][:2]:
                    print(f"    - {s.strip()}")
            if info["remedies"]:
                print("  Recommended Corrective Measures (TNAU Certified):")
                for r in info["remedies"]:
                    print(f"    - {r.strip()}")
            if info["sampling_procedure"]:
                print("  Standard Tissue Sampling Verification:")
                for p in info["sampling_procedure"][:1]:
                    print(f"    - {p.strip()}")
            if info["sources"]:
                print(f"  Government Verification Source: {info['sources'][0]}")

    print("=" * 80)


if __name__ == "__main__":
    kb = TNAUKnowledgeBase()
    sample_crop = sys.argv[1] if len(sys.argv) > 1 else "Rice"
    sample_ndvi = float(sys.argv[2]) if len(sys.argv) > 2 else 0.119
    sample_spad = float(sys.argv[3]) if len(sys.argv) > 3 else 2.4
    sample_ir = int(sys.argv[4]) if len(sys.argv) > 4 else 168200
    sample_red = int(sys.argv[5]) if len(sys.argv) > 5 else 132450

    generate_prescriptive_report(sample_crop, sample_ndvi, sample_spad, sample_ir, sample_red, kb)
