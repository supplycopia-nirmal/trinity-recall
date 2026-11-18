import os
import json
import uuid
import io
import csv
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import logging

from config import settings
from services.jira_service import jira_service
from services.inventory_service import inventory_service
from services.data_service import data_service

logger = logging.getLogger(__name__)

class ActionService:
    """
    Manages operational workflows and notifications for Trinity Health:
    1. Facility Alert (Clinical & Nursing warning)
    2. Inventory Pull (Physical stock pull & quarantine work order)
    3. Order Management Stop (PO hold & cancellation)
    4. Supplier Communication (RMA, Credit, Replacement, Disposition)
    """

    def __init__(self):
        self._actions_file = settings.ACTIONS_LOG_PATH
        self._actions: List[Dict[str, Any]] = []
        self._load_actions()

    def _load_actions(self):
        """Loads logged actions from disk or seeds realistic initial demo records."""
        settings.LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if self._actions_file.exists():
            try:
                with open(self._actions_file, "r", encoding="utf-8") as f:
                    self._actions = json.load(f)
                logger.info(f"Loaded {len(self._actions)} logged actions from {self._actions_file}.")
                return
            except Exception as e:
                logger.warning(f"Could not read actions file: {e}")

        # Seed with initial realistic Trinity Health actions for immediate demo appeal
        self._actions = [
            {
                "id": "ACT-1001",
                "action_type": "FACILITY_ALERT",
                "type_label": "Facility Clinical Alert",
                "status": "Delivered",
                "timestamp": "2026-11-16 08:30:12",
                "facility": "FACILITY-150",
                "facility_display": "Trinity Health Ann Arbor Hospital (MI) [FACILITY-150]",
                "catalog": "367861",
                "product_description": "TUBE BLOOD COLLECTION K2 EDTA 13MM X 75MM 4ML HEMOGARD CLOSURE LAVENDER",
                "manufacturer": "BECTON DICKINSON AND CO",
                "recipient": "dr.patel@trinity-health.org, nursing-leads-annarbor@trinity-health.org",
                "subject": "CRITICAL CLASS I RECALL: Cease Clinical Use - BD Vacutainer 367861",
                "message": "URGENT CLINICAL SAFETY NOTICE: FDA Class I recall issued for BD Vacutainer EDTA tubes due to chemical interference underestimating blood lead levels. All bedside units must immediately cease use.",
                "details": {"risk_class": "Class I", "priority": "High"}
            },
            {
                "id": "ACT-1002",
                "action_type": "INVENTORY_PULL",
                "type_label": "Inventory Quarantine Work Order",
                "status": "Quarantine Verified",
                "timestamp": "2026-11-16 09:15:45",
                "facility": "FACILITY-142",
                "facility_display": "Trinity Health Grand Rapids Hospital (MI) [FACILITY-142]",
                "catalog": "367861",
                "product_description": "TUBE BLOOD COLLECTION K2 EDTA 13MM X 75MM 4ML HEMOGARD CLOSURE LAVENDER",
                "manufacturer": "BECTON DICKINSON AND CO",
                "recipient": "materials.grandrapids@trinity-health.org",
                "subject": "WORK ORDER #WO-9042: Physical Stock Pull & Red-Bin Quarantine",
                "message": "Dispatch materials staff to Central Supply, Clean Utility Rooms, and Phlebotomy carts. Pull all units of catalog 367861 into Quarantine Bay 4. Attach red hazard tags.",
                "details": {"quarantine_bay": "Quarantine Bay 4 (Red Bin)", "units_pulled": 400, "verified_by": "J. Miller (Materials Lead)"}
            },
            {
                "id": "ACT-1003",
                "action_type": "ORDER_STOP",
                "type_label": "Order Management Cancellation Hold",
                "status": "PO Cancelled",
                "timestamp": "2026-11-16 10:02:20",
                "facility": "FACILITY-141",
                "facility_display": "Saint Joseph Health System - Mishawaka (IN) [FACILITY-141]",
                "catalog": "367861",
                "product_description": "TUBE BLOOD COLLECTION K2 EDTA 13MM X 75MM 4ML HEMOGARD CLOSURE LAVENDER",
                "manufacturer": "BECTON DICKINSON AND CO",
                "recipient": "purchasing-holds@trinity-health.org",
                "subject": "PO CANCELLATION NOTICE: Hold and Cancel PO 61350201190",
                "message": "Purchasing violation detected. PO 61350201190 placed for recalled catalog 367861. Immediate EDI 850 cancellation dispatched; dock receiving alert active.",
                "details": {"po_number": "61350201190", "spend_avoided": 6.95, "dock_alert": "Enabled"}
            },
            {
                "id": "ACT-1004",
                "action_type": "SUPPLIER_ACTION",
                "type_label": "Supplier RMA & Credit Request",
                "status": "RMA Pending",
                "timestamp": "2026-11-16 11:40:00",
                "facility": "TRINITY HEALTH SYSTEM-WIDE",
                "facility_display": "Trinity Health System-Wide Supply Chain",
                "catalog": "367861",
                "product_description": "TUBE BLOOD COLLECTION K2 EDTA 13MM X 75MM 4ML HEMOGARD CLOSURE LAVENDER",
                "manufacturer": "BECTON DICKINSON AND CO",
                "recipient": "recalls.coordinator@bd.com, commercial.support@bd.com",
                "subject": "TRINITY HEALTH RECALL CLAIM: Request for RMA, Credit Memo & Disposition for Cat 367861",
                "message": "Trinity Health has identified multiple affected POs for BD Vacutainer 367861. We request formal RMA documentation, prepaid return shipping labels, and immediate 100% credit memo.",
                "details": {"supplier_action_type": "RMA & Credit Request", "claim_amount": 12845.50, "rma_number": "PENDING-BD-994"}
            }
        ]
        self._save_actions()

    def _save_actions(self):
        """Persists actions to local JSON."""
        try:
            with open(self._actions_file, "w", encoding="utf-8") as f:
                json.dump(self._actions, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving actions log: {e}")

    def get_actions(self, action_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns logged actions sorted newest first."""
        if not action_type or action_type == "ALL":
            return sorted(self._actions, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
        return sorted([a for a in self._actions if a.get("action_type") == action_type], key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]

    def _generate_lots_manifest(self, catalog: str, facility: str, manufacturer: str) -> tuple[Dict[str, Any], bytes]:
        """
        Simulates granular physical inventory lots for the catalog & facility,
        returning the inventory simulation dict and a CSV manifest in UTF-8 bytes.
        """
        inv_data = inventory_service.simulate_inventory(
            catalog=catalog,
            facility=facility,
            manufacturer=manufacturer
        )
        lots = inv_data.get("inventory_lots", [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Facility ID",
            "Catalog #",
            "Manufacturer",
            "Lot Number",
            "Serial Number",
            "Expiration Date",
            "Quantity (Units)",
            "Clinical Department",
            "Storage Tier",
            "Aisle / Shelf / Bin Address",
            "UDI Barcode (GS1-128)",
            "Quarantine Status"
        ])

        for lot in lots:
            loc = lot.get("location", {})
            writer.writerow([
                facility,
                catalog,
                manufacturer,
                lot.get("lot_number", ""),
                lot.get("serial_number", ""),
                lot.get("expiration_date", ""),
                lot.get("quantity", 0),
                loc.get("department", ""),
                loc.get("tier", ""),
                loc.get("full_address", "").replace("&bull;", "•"),
                lot.get("udi_barcode", ""),
                lot.get("status", "RECALL_QUARANTINED")
            ])

        csv_bytes = output.getvalue().encode("utf-8")
        return inv_data, csv_bytes

    def notify_facility(
        self,
        facility: str,
        facility_display: str,
        catalog: str,
        product_description: str,
        manufacturer: str,
        recipient: str,
        subject: str,
        message: str,
        risk_class: str = "Class II",
        sync_jira: bool = True
    ) -> Dict[str, Any]:
        """Dispatches an urgent clinical notice to a hospital facility and syncs to Jira TRM."""
        act_id = f"ACT-{len(self._actions) + 1001}"
        
        jira_ticket = None
        inv_data, csv_bytes = self._generate_lots_manifest(catalog, facility, manufacturer)
        on_hand = inv_data.get("on_hand_units", 0)

        if sync_jira:
            extra_details = {
                "on_hand_units": on_hand,
                "quarantine_location": "Clinical Department Holding Bins & Storeroom",
                "action_message": f"Subject: {subject}\n\n{message}"
            }
            csv_attachment = {
                "filename": f"affected_lots_{catalog}_{facility}.csv",
                "bytes": csv_bytes
            }
            jira_ticket = jira_service.create_recall_case(
                catalog=catalog,
                product_description=product_description,
                manufacturer=manufacturer,
                risk_class=risk_class,
                facility=facility_display,
                recall_reason=message[:400],
                lifecycle_step="Step 4: Contain Exposure",
                accountable_role="Clinical Service Owner & Quality Lead",
                action_type="CLINICAL_ALERT",
                summary_override=f"[{risk_class}] Clinical Cease-Use Alert: {catalog} ({facility_display})",
                extra_details=extra_details,
                csv_attachment_data=csv_attachment
            )

        record = {
            "id": act_id,
            "action_type": "FACILITY_ALERT",
            "type_label": "Facility Clinical Alert",
            "status": "Delivered",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "facility": facility,
            "facility_display": facility_display,
            "catalog": catalog,
            "product_description": product_description,
            "manufacturer": manufacturer,
            "recipient": recipient,
            "subject": subject,
            "message": message,
            "jira_key": jira_ticket.get("key") if jira_ticket and jira_ticket.get("success") else None,
            "jira_url": jira_ticket.get("url") if jira_ticket and jira_ticket.get("success") else None,
            "details": {
                "risk_class": risk_class,
                "priority": "Critical" if "I" in risk_class else "Standard",
                "lifecycle_step": "Step 4: Contain Exposure",
                "acknowledged": False
            }
        }
        self._actions.insert(0, record)
        self._save_actions()
        return record

    def notify_inventory(
        self,
        facility: str,
        facility_display: str,
        catalog: str,
        product_description: str,
        manufacturer: str,
        recipient: str,
        subject: str,
        message: str,
        quarantine_location: str = "Quarantine Bay 1 - Red Bin",
        estimated_units: float = 0,
        sync_jira: bool = True
    ) -> Dict[str, Any]:
        """Dispatches a stock pull work order to hospital materials management and syncs to Jira TRM."""
        act_id = f"ACT-{len(self._actions) + 1001}"
        wo_num = f"WO-{uuid.uuid4().hex[:6].upper()}"
        
        jira_ticket = None
        inv_data, csv_bytes = self._generate_lots_manifest(catalog, facility, manufacturer)
        effective_units = estimated_units if estimated_units > 0 else inv_data.get("on_hand_units", 0)

        if sync_jira:
            extra_details = {
                "on_hand_units": effective_units,
                "quarantine_location": quarantine_location,
                "action_message": f"Work Order #{wo_num}\nRecipient: {recipient}\n\n{message}"
            }
            csv_attachment = {
                "filename": f"quarantine_lots_{catalog}_{facility}.csv",
                "bytes": csv_bytes
            }
            jira_ticket = jira_service.create_recall_case(
                catalog=catalog,
                product_description=product_description,
                manufacturer=manufacturer,
                risk_class="Class I",
                facility=facility_display,
                recall_reason=f"Stock pull required: {effective_units} units into {quarantine_location}. Directives: {message[:300]}",
                lifecycle_step="Step 4: Contain Exposure",
                accountable_role="Supply Chain Lead & Materials Manager",
                action_type="INVENTORY_PULL",
                summary_override=f"Stock Pull & Quarantine WO #{wo_num}: {catalog} ({facility_display})",
                extra_details=extra_details,
                csv_attachment_data=csv_attachment
            )

        record = {
            "id": act_id,
            "action_type": "INVENTORY_PULL",
            "type_label": "Inventory Quarantine Work Order",
            "status": "Work Order Dispatched",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "facility": facility,
            "facility_display": facility_display,
            "catalog": catalog,
            "product_description": product_description,
            "manufacturer": manufacturer,
            "recipient": recipient,
            "subject": subject,
            "message": message,
            "jira_key": jira_ticket.get("key") if jira_ticket and jira_ticket.get("success") else None,
            "jira_url": jira_ticket.get("url") if jira_ticket and jira_ticket.get("success") else None,
            "details": {
                "quarantine_location": quarantine_location,
                "estimated_units": estimated_units,
                "work_order_num": wo_num,
                "lifecycle_step": "Step 4: Contain Exposure",
                "pull_status": "In Progress"
            }
        }
        self._actions.insert(0, record)
        self._save_actions()
        return record

    def notify_order_management(
        self,
        facility: str,
        facility_display: str,
        catalog: str,
        product_description: str,
        manufacturer: str,
        recipient: str,
        subject: str,
        message: str,
        po_number: Optional[str] = None,
        total_spend: float = 0,
        sync_jira: bool = True
    ) -> Dict[str, Any]:
        """Dispatches order hold / PO cancellation to Purchasing & Order Management and syncs to Jira TRM."""
        act_id = f"ACT-{len(self._actions) + 1001}"
        po_label = po_number or "All Open POs"

        jira_ticket = None
        inv_data, csv_bytes = self._generate_lots_manifest(catalog, facility, manufacturer)

        if sync_jira:
            extra_details = {
                "po_number": po_label,
                "spend_avoided": total_spend,
                "action_message": f"PO Hold Directive: {po_label}\nSpend at Risk: ${total_spend:,.2f}\n\n{message}"
            }
            csv_attachment = {
                "filename": f"po_hold_lots_{catalog}_{facility}.csv",
                "bytes": csv_bytes
            }
            jira_ticket = jira_service.create_recall_case(
                catalog=catalog,
                product_description=product_description,
                manufacturer=manufacturer,
                risk_class="Class II",
                facility=facility_display,
                recall_reason=f"Purchasing violation detected: Stop and cancel PO {po_label}. Avoid spend: ${total_spend:,.2f}",
                lifecycle_step="Step 4: Contain Exposure",
                accountable_role="Supply Chain Lead & Purchasing Operations",
                action_type="ORDER_STOP",
                summary_override=f"PO Cancel Hold #{po_label}: {catalog} ({facility_display})",
                extra_details=extra_details,
                csv_attachment_data=csv_attachment
            )

        record = {
            "id": act_id,
            "action_type": "ORDER_STOP",
            "type_label": "Order Management Cancellation Hold",
            "status": "Order Hold Placed",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "facility": facility,
            "facility_display": facility_display,
            "catalog": catalog,
            "product_description": product_description,
            "manufacturer": manufacturer,
            "recipient": recipient,
            "subject": subject,
            "message": message,
            "jira_key": jira_ticket.get("key") if jira_ticket and jira_ticket.get("success") else None,
            "jira_url": jira_ticket.get("url") if jira_ticket and jira_ticket.get("success") else None,
            "details": {
                "po_number": po_label,
                "spend_avoided": total_spend,
                "lifecycle_step": "Step 4: Contain Exposure",
                "edi_block": "Active (EDI 850/855 Suspended)",
                "dock_receiving_block": "Active"
            }
        }
        self._actions.insert(0, record)
        self._save_actions()
        return record

    def send_supplier_message(
        self,
        manufacturer: str,
        catalog: str,
        product_description: str,
        supplier_action_type: str,
        recipient: str,
        subject: str,
        message: str,
        claim_amount: float = 0,
        facility: str = "SYSTEM-WIDE",
        sync_jira: bool = True
    ) -> Dict[str, Any]:
        """Sends a formal supplier action request (RMA, Credit, Replacement, Disposition) and syncs to Jira TRM."""
        act_id = f"ACT-{len(self._actions) + 1001}"
        ref_ticket = f"TRN-SUP-{uuid.uuid4().hex[:6].upper()}"

        jira_ticket = None
        if sync_jira:
            jira_ticket = jira_service.create_recall_case(
                catalog=catalog,
                product_description=product_description,
                manufacturer=manufacturer,
                risk_class="Class II",
                facility=facility,
                recall_reason=f"Supplier action demand: {supplier_action_type}. Claim amount: ${claim_amount:,.2f}",
                lifecycle_step="Step 7: Correct or Dispose",
                accountable_role="Central Recall Program Owner & Vendor Lead",
                action_type="SUPPLIER_ACTION",
                summary_override=f"Supplier Claim #{ref_ticket}: {supplier_action_type} - {manufacturer} ({catalog})"
            )

        record = {
            "id": act_id,
            "action_type": "SUPPLIER_ACTION",
            "type_label": f"Supplier {supplier_action_type}",
            "status": "Notice Sent",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "facility": facility,
            "facility_display": "Trinity Health Supply Chain Operations",
            "catalog": catalog,
            "product_description": product_description,
            "manufacturer": manufacturer,
            "recipient": recipient,
            "subject": subject,
            "message": message,
            "jira_key": jira_ticket.get("key") if jira_ticket and jira_ticket.get("success") else None,
            "jira_url": jira_ticket.get("url") if jira_ticket and jira_ticket.get("success") else None,
            "details": {
                "supplier_action_type": supplier_action_type,
                "claim_amount": claim_amount,
                "reference_ticket": ref_ticket,
                "lifecycle_step": "Step 7: Correct or Dispose",
                "rma_status": "Awaiting Vendor Acknowledgment"
            }
        }
        self._actions.insert(0, record)
        self._save_actions()
        return record

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Calculates action counts for dashboard badges."""
        facility_alerts = sum(1 for a in self._actions if a.get("action_type") == "FACILITY_ALERT")
        inventory_pulls = sum(1 for a in self._actions if a.get("action_type") == "INVENTORY_PULL")
        order_stops = sum(1 for a in self._actions if a.get("action_type") == "ORDER_STOP")
        supplier_actions = sum(1 for a in self._actions if a.get("action_type") == "SUPPLIER_ACTION")
        return {
            "total_actions": len(self._actions),
            "facility_alerts": facility_alerts,
            "inventory_pulls": inventory_pulls,
            "order_stops": order_stops,
            "supplier_actions": supplier_actions
        }


action_service = ActionService()
