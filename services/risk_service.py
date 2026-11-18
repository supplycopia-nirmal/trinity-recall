"""
Healthcare Disruption & Clinical Hazard Risk Scoring Engine
Ported from Cardinal Health Command Center (Project Mosaic 4-Vector Model).

Formula:
Risk Index = (w_reg * S_reg) + (w_inv * S_inv) + (w_ext * S_ext) + (w_clin * S_clin)

Default weights:
- w_reg (Regulatory Vector): 0.35
- w_inv (Inventory Vector): 0.30
- w_ext (External Threat Vector): 0.20
- w_clin (Clinical Criticality Vector): 0.15
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

class RiskService:
    def __init__(self):
        self.w_reg = 0.35
        self.w_inv = 0.30
        self.w_ext = 0.20
        self.w_clin = 0.15

    def get_weights(self) -> Dict[str, float]:
        return {
            "w_reg": self.w_reg,
            "w_inv": self.w_inv,
            "w_ext": self.w_ext,
            "w_clin": self.w_clin
        }

    def calculate_risk(
        self,
        fda_classification: str,
        product_desc: str = "",
        gmdn_or_segment: str = "",
        days_of_supply: float = 30.0,
        has_external_threat: bool = False,
        is_shortage: bool = False,
        has_tariff: bool = False,
        quantity: float = 100.0,
        daily_usage: float = 10.0,
        po_date: str = "",
        fda_recall_date: str = ""
    ) -> Dict[str, Any]:
        """
        Calculates multi-vector risk, factor breakdown, prediction horizon,
        prediction confidence, and active operational anomaly flags.
        """
        c_upper = str(fda_classification).upper()

        # 1. Regulatory Vector (S_reg) [0 - 100]
        if "CLASS I" in c_upper and "CLASS II" not in c_upper and "CLASS III" not in c_upper:
            s_reg = 100
        elif "CLASS II" in c_upper and "CLASS III" not in c_upper:
            s_reg = 60
        elif "CLASS III" in c_upper:
            s_reg = 30
        else:
            s_reg = 20

        # 2. Inventory Vector (S_inv) [0 - 100]
        # Evaluates Days of Supply (DoS) runway
        if days_of_supply <= 7.0:
            s_inv = 100
        elif days_of_supply <= 14.0:
            s_inv = 75
        elif days_of_supply <= 30.0:
            s_inv = 40
        else:
            s_inv = 10

        # 3. External Threat Vector (S_ext) [0 - 100]
        # Ingests allocation caps, FDA device shortages, and purchasing breaches
        s_ext = 0
        if has_external_threat:  # Allocation constraint or purchasing violation active
            s_ext += 50
        if is_shortage:          # Listed on FDA Device Shortages
            s_ext += 30
        if has_tariff:           # HTS tariff rate increase
            s_ext += 20
        s_ext = min(100, s_ext)

        # 4. Clinical Criticality Vector (S_clin) [0 - 100]
        combined_text = (str(product_desc) + " " + str(gmdn_or_segment)).upper()
        implant_keywords = ["IMPLANT", "GRAFT", "STENT", "PACEMAKER", "PROSTHESIS", "MESH", "VALVE", "DEFIBRILLATOR", "BALLOON", "CATHETER"]
        surgical_keywords = ["SURGICAL", "SYRINGE", "NEEDLE", "DRAPE", "SUTURE", "SUCTION", "TRAUMA", "CATH LAB", "ANESTHESIA", "TROCAR", "TUBE", "KIT", "PACK", "PUMP", "MONITOR", "BLADE"]

        if any(k in combined_text for k in implant_keywords):
            s_clin = 100  # High-risk invasive/implantable
        elif any(k in combined_text for k in surgical_keywords):
            s_clin = 65   # Vital surgical/procedure consumable
        else:
            s_clin = 30   # Routine general supply

        # Composite Weighted Disruption Index
        raw_score = (self.w_reg * s_reg) + (self.w_inv * s_inv) + (self.w_ext * s_ext) + (self.w_clin * s_clin)
        score = int(round(min(100, max(0, raw_score))))

        # Determine Severity Tier
        if score >= 75:
            severity = "Critical"
            action_code = "IMMEDIATE_ACTION_REQUIRED"
        elif score >= 40:
            severity = "Medium"
            action_code = "QUARANTINE_AND_SUBSTITUTE"
        else:
            severity = "Low"
            action_code = "MONITOR_INVENTORY"

        # Prediction Horizon
        if days_of_supply <= 30.0 or score >= 75:
            horizon = "30_days"
            horizon_label = "30-Day Critical"
        elif days_of_supply <= 60.0:
            horizon = "60_days"
            horizon_label = "60-Day Mid-Range"
        else:
            horizon = "90_days"
            horizon_label = "90-Day Strategic"

        # Prediction Confidence
        if score >= 75 or s_reg == 100:
            confidence = {"level": "High", "percentage": 96, "band": "High (94-98%)"}
        elif score >= 40:
            confidence = {"level": "Medium", "percentage": 85, "band": "Medium (82-89%)"}
        else:
            confidence = {"level": "Low", "percentage": 72, "band": "Low (65-75%)"}

        return {
            "score": score,
            "severity": severity,
            "action_code": action_code,
            "horizon": horizon,
            "horizon_label": horizon_label,
            "confidence": confidence,
            "factors": {
                "regulatory_score": s_reg,
                "inventory_exposure_score": s_inv,
                "external_threat_score": s_ext,
                "clinical_criticality_score": s_clin
            },
            "weights_used": self.get_weights()
        }

risk_service = RiskService()
