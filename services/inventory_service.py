import hashlib
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

class InventorySimulatorService:
    """
    Multi-Tier Clinical Inventory Simulation Engine for Trinity Health.
    
    Generates realistic, operational hospital inventory data points:
    - Lot numbers, serial numbers, expiration dates
    - Multi-tier clinical storage locations (Central Sterile Processing vs OR Suites vs Cath Lab vs Pyxis)
    - Department, Aisle, Shelf, Bin, and Tote locations
    - GS1-128 compliant UDI barcodes
    - Quarantined (Red Bin) vs. Safe usable lot distributions
    - Interactive lot quarantine hold/release actions
    - On-hand pre-approved clinical substitutes available in storeroom/DC buffer
    
    Deterministically seeded by (facility_id, catalog_number) for consistent repeatability.
    """
    
    DEPARTMENTS_CONFIG = [
        {
            "tier": "Central Sterile Distribution (CSD)",
            "departments": ["Central Sterile Processing (CSP)", "Main Supply Storeroom", "Bulk Logistics Staging"],
            "aisles": ["Aisle 1", "Aisle 2", "Aisle 3", "Aisle 4", "Bulk Pallet Bay C"],
            "shelves": ["Shelf A", "Shelf B", "Shelf C", "Shelf D"],
            "bins": ["Bin 04", "Bin 12", "Bin 14", "Bin 22", "Tote 108"]
        },
        {
            "tier": "Point-of-Use Clinical Storage",
            "departments": ["Main Surgical Suite OR-2", "Main Surgical Suite OR-4", "Cath Lab Staging Unit", "Trauma / ED Pyxis Station", "ICU Clean Utility 3A"],
            "aisles": ["Omnicell Locker Unit 1", "Pyxis MedStation Unit 2", "Procedure Cart Alpha", "Supply Wall Rack 4"],
            "shelves": ["Drawer 1", "Drawer 2", "Drawer 3", "Tier 2 Shelf"],
            "bins": ["Pocket 08", "Pocket 12", "Bin Blue-03", "Cassette 4A"]
        }
    ]
    
    SUBSTITUTION_EQUIVALENTS = {
        "367861": [
            {
                "substitute_catalog": "GRE-456043",
                "product_description": "VACUETTE 4mL K2EDTA Blood Collection Tube Lavender Cap",
                "manufacturer": "GREINER BIO-ONE",
                "base_units": 480,
                "tier_location": "Central Lab Specimen Processing - Shelf B - Bin 02",
                "clinical_match_pct": 98.5,
                "gpo_price_delta": -0.15,
                "savings_pct": 10.0,
                "availability": "IN_STOCK_SAME_FACILITY"
            },
            {
                "substitute_catalog": "CAH-EDTA-400",
                "product_description": "Monoject 4mL K3EDTA Lavender Stopper Blood Tube",
                "manufacturer": "CARDINAL HEALTH",
                "base_units": 950,
                "tier_location": "Trinity Health Regional DC (Buffer)",
                "clinical_match_pct": 96.0,
                "gpo_price_delta": -0.22,
                "savings_pct": 14.0,
                "availability": "REGIONAL_DC_BUFFER_READY"
            }
        ],
        "W1DR01": [
            {
                "substitute_catalog": "BSX-AC8802",
                "product_description": "ACCOLADE MRI Dual-Chamber Pacemaker L131 Bi-Directional",
                "manufacturer": "BOSTON SCIENTIFIC CORP",
                "base_units": 24,
                "tier_location": "Cath Lab Staging Unit - Secure Implant Vault 2",
                "clinical_match_pct": 99.0,
                "gpo_price_delta": -120.00,
                "savings_pct": 3.2,
                "availability": "IN_STOCK_SAME_FACILITY"
            },
            {
                "substitute_catalog": "ABT-PM2120",
                "product_description": "Assurity MRI Dual-Chamber Pacemaker Wireless Telemetry",
                "manufacturer": "ABBOTT",
                "base_units": 45,
                "tier_location": "Trinity Health Regional DC (Buffer)",
                "clinical_match_pct": 97.0,
                "gpo_price_delta": +45.00,
                "savings_pct": -1.2,
                "availability": "REGIONAL_DC_BUFFER_READY"
            }
        ],
        "DTPA2QQ": [
            {
                "substitute_catalog": "BSX-RES-HF",
                "product_description": "RESONATE HF Quad CRT-D MRI SureScan Cardiac Resynchronization",
                "manufacturer": "BOSTON SCIENTIFIC CORP",
                "base_units": 18,
                "tier_location": "Cath Lab Vault - Safe C",
                "clinical_match_pct": 99.0,
                "gpo_price_delta": -350.00,
                "savings_pct": 4.5,
                "availability": "IN_STOCK_SAME_FACILITY"
            }
        ],
        "446252": [
            {
                "substitute_catalog": "CH-BD-4400",
                "product_description": "Cardinal Health Polypropylene Syringe 10mL Luer-Lok",
                "manufacturer": "CARDINAL HEALTH",
                "base_units": 1200,
                "tier_location": "CSD - Aisle 2 - Shelf B - Bin 18",
                "clinical_match_pct": 100.0,
                "gpo_price_delta": -0.08,
                "savings_pct": 18.0,
                "availability": "IN_STOCK_SAME_FACILITY"
            }
        ]
    }
    
    def __init__(self):
        # In-memory store for user lot status mutations (Hold / Release)
        self._quarantine_overrides: Dict[str, str] = {}
        
    def _get_seed(self, facility: str, catalog: str) -> int:
        key = f"{str(facility).strip().upper()}::{str(catalog).strip().upper()}"
        return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
        
    def _derive_mfg_code(self, mfg: str) -> str:
        words = [w for w in str(mfg).replace(",", "").replace(".", "").split() if w.upper() not in ["AND", "CO", "INC", "CORP", "LP", "LLC"]]
        if not words:
            return "MED"
        if len(words) == 1:
            return words[0][:3].upper()
        return "".join(w[0] for w in words[:3]).upper()
        
    def _split_quantity(self, total: int, num_splits: int, rng: random.Random) -> List[int]:
        if num_splits <= 1 or total <= 1:
            return [total]
        cuts = sorted(rng.sample(range(1, total), num_splits - 1))
        parts = []
        prev = 0
        for c in cuts:
            parts.append(c - prev)
            prev = c
        parts.append(total - prev)
        return parts

    def simulate_inventory(
        self,
        catalog: str,
        facility: str = "FACILITY-150",
        product_description: str = "",
        manufacturer: str = "",
        base_on_hand: Optional[float] = None,
        base_burn_rate: Optional[float] = None,
        is_recalled: bool = True,
        fda_event_id: str = "79223",
        fda_classification: str = "Class II",
        uom: str = "EA"
    ) -> Dict[str, Any]:
        """
        Generates simulated physical inventory profile:
        on-hand counts, quarantine bins, granular lot breakdown, and pre-approved substitutes.
        """
        seed = self._get_seed(facility, catalog)
        rng = random.Random(seed)
        
        if base_on_hand is not None and base_on_hand > 0:
            total_on_hand = int(base_on_hand)
        else:
            total_on_hand = rng.randint(48, 480)
            
        if base_burn_rate is not None and base_burn_rate > 0:
            burn_rate = float(base_burn_rate)
        else:
            burn_rate = max(1.0, round(total_on_hand / rng.uniform(8.0, 35.0), 1))
            
        days_of_supply = round(total_on_hand / burn_rate, 1) if burn_rate > 0 else 30.0
        
        num_lots = rng.randint(2, 4)
        lot_sizes = self._split_quantity(total_on_hand, num_lots, rng)
        
        mfg_prefix = self._derive_mfg_code(manufacturer)
        cat_clean = catalog.replace("-", "")[:4].upper()
        
        now = datetime.now()
        inventory_lots = []
        
        quarantined_units_total = 0
        cleared_units_total = 0
        
        for idx, qty in enumerate(lot_sizes):
            lot_code_num = rng.randint(1000, 9999)
            lot_suffix = chr(65 + idx)
            lot_number = f"LOT-{now.year}{mfg_prefix}-{lot_code_num}{lot_suffix}"
            serial_number = f"SN-{mfg_prefix}-{cat_clean}{rng.randint(10000, 99999)}"
            
            exp_days = rng.randint(180, 1095)
            exp_date = (now + timedelta(days=exp_days)).strftime("%Y-%m-%d")
            exp_yymmdd = (now + timedelta(days=exp_days)).strftime("%y%m%d")
            
            gtin = f"0088{rng.randint(10000000, 99999999)}"
            udi_barcode = f"(01){gtin}(17){exp_yymmdd}(10){lot_code_num}{lot_suffix}(21){serial_number[-5:]}"
            
            loc_config = self.DEPARTMENTS_CONFIG[idx % len(self.DEPARTMENTS_CONFIG)]
            dept = rng.choice(loc_config["departments"])
            aisle = rng.choice(loc_config["aisles"])
            shelf = rng.choice(loc_config["shelves"])
            bin_loc = rng.choice(loc_config["bins"])
            full_address = f"{dept} &bull; {aisle} &bull; {shelf} &bull; {bin_loc}"
            
            override_key = f"{facility}::{catalog}::{lot_number}"
            if override_key in self._quarantine_overrides:
                status = self._quarantine_overrides[override_key]
                affected = (status == "RECALL_QUARANTINED")
            else:
                if is_recalled:
                    affected = True if idx == 0 else (rng.random() < 0.45)
                else:
                    affected = False
                status = "RECALL_QUARANTINED" if affected else "AVAILABLE"
                
            if status == "RECALL_QUARANTINED":
                quarantined_units_total += qty
            else:
                cleared_units_total += qty
                
            inventory_lots.append({
                "lot_number": lot_number,
                "serial_number": serial_number,
                "expiration_date": exp_date,
                "quantity": qty,
                "location": {
                    "tier": loc_config["tier"],
                    "department": dept,
                    "aisle": aisle,
                    "shelf": shelf,
                    "bin": bin_loc,
                    "full_address": full_address
                },
                "quarantine_status": status,
                "is_recall_affected": affected,
                "udi_barcode": udi_barcode,
                "quarantine_bay": "Quarantine Bay 1 (Red Bin - Hazard Tag)" if status == "RECALL_QUARANTINED" else "Active Storeroom Par Bin"
            })
            
        usable_units = max(0, total_on_hand - quarantined_units_total)
        usable_dos = round(usable_units / burn_rate, 1) if burn_rate > 0 else 0.0
        
        # Pull pre-approved substitutes if defined, or generate deterministic alternatives
        configured_subs = self.SUBSTITUTION_EQUIVALENTS.get(catalog, [])
        if not configured_subs:
            configured_subs = [
                {
                    "substitute_catalog": f"SUB-{cat_clean}-A",
                    "product_description": f"Direct Therapeutic Alternative for {product_description[:35]}",
                    "manufacturer": "PRE-APPROVED HEALTH SYSTEM SUPPLIER",
                    "base_units": rng.randint(50, 300),
                    "tier_location": "Main Storeroom - Clean Supply Buffer Shelf C",
                    "clinical_match_pct": round(rng.uniform(94.0, 99.0), 1),
                    "gpo_price_delta": -round(rng.uniform(5.0, 45.0), 2),
                    "savings_pct": round(rng.uniform(3.0, 12.0), 1),
                    "availability": "IN_STOCK_SAME_FACILITY"
                }
            ]

        return {
            "catalog": catalog,
            "facility": facility,
            "product_description": product_description,
            "manufacturer": manufacturer,
            "uom": uom,
            "total_on_hand_units": total_on_hand,
            "quarantined_units": quarantined_units_total,
            "usable_units": usable_units,
            "daily_usage_rate": burn_rate,
            "days_of_supply": days_of_supply,
            "usable_days_of_supply": usable_dos,
            "inventory_lots": inventory_lots,
            "substitutions_available_in_inventory": configured_subs
        }

    def update_lot_quarantine_status(self, facility: str, catalog: str, lot_number: str, new_status: str) -> bool:
        """Mutates lot quarantine status (e.g. nurse or supply manager clicks Hold/Release)."""
        override_key = f"{facility}::{catalog}::{lot_number}"
        self._quarantine_overrides[override_key] = new_status
        return True

inventory_service = InventorySimulatorService()
