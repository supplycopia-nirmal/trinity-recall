import logging
from typing import Dict, Any, Optional
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)

class ClinicalMemoService:
    """
    AI-powered Clinical Safety Memo & Directive Generator.
    Crafts comprehensive, hospital-grade clinical cease-use memos and executive notifications
    grounded in FDA recall hazard mechanisms, affected lot numbers, and facility inventory impact.
    """

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
        self._client = None
        if self.api_key:
            try:
                self._client = OpenAI(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize OpenAI client: {e}")

    def is_available(self) -> bool:
        return self._client is not None

    def generate_clinical_memo(
        self,
        catalog: str,
        facility: str,
        facility_display: str,
        product_description: str,
        manufacturer: str,
        risk_class: str = "Class I",
        recall_reason: str = "",
        affected_lots_summary: str = "",
        estimated_units: float = 0,
        substitute_info: str = ""
    ) -> Dict[str, str]:
        """
        Generates a professional, structured clinical memo with tailored Subject and Body.
        """
        # If OpenAI client is available, generate via LLM
        if self._client:
            prompt = f"""You are the Chief Medical Officer and Director of Patient Safety & Supply Chain at Trinity Health System.
A critical medical device / pharmaceutical recall has been identified affecting one of our hospital facilities.

Please draft an authoritative, urgent Clinical Safety Memo for nursing leadership, chief medical officers, operating room directors, and pharmacy/materials leads.

RECALL CONTEXT:
- Target Hospital Facility: {facility_display}
- Product Catalog #: {catalog}
- Description: {product_description}
- Manufacturer: {manufacturer}
- FDA Classification: {risk_class} (Urgent)
- FDA Reason for Recall / Clinical Hazard: {recall_reason}
- Affected Lot Parameters: {affected_lots_summary or "All lots currently in circulation"}
- On-Hand Physical Exposure: {estimated_units} units identified in hospital inventory
- Pre-Approved Clinical Substitutes: {substitute_info or "Formulary-matched alternatives available in Central Supply buffer"}

OUTPUT REQUIREMENTS:
1. Provide a clear, urgent SUBJECT line (starts with [CRITICAL CLINICAL DIRECTIVE] or [URGENT PATIENT SAFETY ALERT]).
2. Provide a structured, highly detailed BODY formatted cleanly with clear sections:
   - EXECUTIVE SUMMARY & REGULATORY HAZARD
   - CLINICAL IMPLICATIONS & MECHANISM OF FAILURE
   - IMMEDIATE BEDSIDE DIRECTIVES (Step-by-step for floor nurses, surgical teams, and clinicians)
   - PHYSICAL QUARANTINE & FLOOR SWEEP PROTOCOL
   - PATIENT SAFETY MONITORING & RETROSPECTIVE SURVEILLANCE
   - APPROVED FORMULARY ALTERNATIVES
   - EMERGENCY CONTACTS & INCIDENT REPORTING

Do not include markdown triple-backtick blocks in the overall response. Return your response in this exact format:
SUBJECT: <the subject line>
BODY:
<the memo body>
"""
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a clinical safety expert and chief hospital epidemiologist drafting rigorous patient safety memos for Trinity Health."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=900
                )
                content = resp.choices[0].message.content.strip()
                if "SUBJECT:" in content and "BODY:" in content:
                    parts = content.split("BODY:", 1)
                    subj = parts[0].replace("SUBJECT:", "").strip()
                    body = parts[1].strip()
                    return {"subject": subj, "body": body}
                else:
                    return {
                        "subject": f"URGENT [{risk_class}] CLINICAL SAFETY DIRECTIVE: Cease Clinical Use of Cat {catalog} ({manufacturer})",
                        "body": content
                    }
            except Exception as e:
                logger.error(f"OpenAI generation error: {e}. Falling back to deterministic clinical memo.")

        # Deterministic High-Quality Fallback
        subject = f"URGENT [{risk_class}] CLINICAL SAFETY DIRECTIVE: Immediate Cease-Use of {catalog} - {manufacturer}"
        body = f"""ATTENTION: Chief Medical Officer, Chief Nursing Officer, Surgical Chairs, and Materials Management
LOCATION: {facility_display}
DATE: {catalog} Recall Notice
CLASSIFICATION: FDA {risk_class} - High Clinical Priority

1. EXECUTIVE SUMMARY & REGULATORY HAZARD
The FDA and manufacturer {manufacturer} have issued a critical recall for Product Catalog #{catalog}: {product_description}.
Failure Mechanism / Stated Hazard: {recall_reason}

2. IMMEDIATE BEDSIDE DIRECTIVES
All clinical personnel must immediately execute the following mandatory containment steps:
• Cease bedside, surgical, and clinical utilization of Catalog #{catalog} across all inpatient floors, procedural suites, and ambulatory clinics.
• Inspect all point-of-use storage, Pyxis units, Omnicell lockers, crash carts, and sterile procedure trays.
• Immediately remove all identified units and hand over to Materials Management.
• Do NOT return affected inventory to standard clean utility rooms or par supply carts.

3. PHYSICAL QUARANTINE & MATERIALS SWEEP
• Materials Management has dispatched a dedicated sweep team to collect all physical units (estimated on-hand: {estimated_units} units).
• All retrieved items must be transferred to the facility's Designated Secured Quarantine Bay and affixed with Bright Red FDA Quarantine Tags.
• Electronic item masters and barcode scanning systems have been updated to reject EDI 850 purchasing orders and block dock receiving.

4. PATIENT SURVEILLANCE & CLINICAL MONITORING
• Attending physicians who have utilized this product within the past 30 days must review patient medical records (MRNs) for potential adverse reactions related to: {recall_reason}.
• Complete any required clinical surveillance documentation in Epic EHR under the Hospital Recall Protocol.

5. APPROVED CLINICAL ALTERNATIVES & SUPPORT
• {substitute_info or "Pre-approved clinical bio-equivalents are staged in Central Sterile Processing and available for immediate requisition."}
• For emergency clinical consultations, contact the Hospital Safety Officer or Pharmacy Recall Coordinator immediately.

[Synthesized by SupplyCopia Ask The Bee Enterprise Safety Co-Pilot]"""

        return {"subject": subject, "body": body}

    def generate_supplier_demand(
        self,
        manufacturer: str,
        catalog: str,
        product_description: str,
        claim_amount: float,
        action_type: str = "RMA Return & 100% Credit Claim"
    ) -> Dict[str, str]:
        """
        Generates an authoritative commercial and regulatory demand letter to a medical device supplier
        for immediate RMA return labels, credit memo processing, or replacement inventory.
        """
        claim_formatted = f"${claim_amount:,.2f}"
        if self._client:
            prompt = f"""You are the Vice President of Strategic Sourcing & Supply Chain Operations at Trinity Health System.
A clinical product recall has impacted our hospital network. We are issuing an official commercial demand to the manufacturer.

SUPPLIER / RECALL DETAILS:
- Manufacturer: {manufacturer}
- Catalog Number: {catalog}
- Product Description: {product_description}
- Action Requested: {action_type}
- Total Audited Claim / Spend Value: {claim_formatted}

REQUIREMENTS:
1. Provide an official SUBJECT line for formal correspondence.
2. Draft an executive, legally sound, and assertive commercial demand letter requesting:
   - Immediate Return Material Authorization (RMA) issuance with pre-paid return shipping containers and freight waybills.
   - 100% financial credit memo totaling {claim_formatted} credited against our master AP account.
   - Immediate verification of non-affected lot replacements if required.
   - Strict 48-hour SLA deadline for compliance under our Group Purchasing / Master Supply Agreement.

Do not include markdown triple-backtick blocks. Return in format:
SUBJECT: <subject>
BODY:
<body>
"""
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an executive healthcare supply chain officer and legal contracting specialist drafting official supplier demand letters for Trinity Health."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=600
                )
                content = resp.choices[0].message.content.strip()
                if "SUBJECT:" in content and "BODY:" in content:
                    parts = content.split("BODY:", 1)
                    return {
                        "subject": parts[0].replace("SUBJECT:", "").strip(),
                        "body": parts[1].strip()
                    }
                else:
                    return {
                        "subject": f"TRINITY HEALTH OFFICIAL RECALL DEMAND: {action_type} - Cat #{catalog} ({manufacturer})",
                        "body": content
                    }
            except Exception as e:
                logger.error(f"OpenAI supplier demand error: {e}. Using deterministic letter.")

        subject = f"TRINITY HEALTH OFFICIAL DEMAND: {action_type} - Catalog #{catalog} ({manufacturer})"
        body = f"""ATTENTION: Director of Quality Assurance, Regulatory Affairs & Recall Compliance
SUPPLIER: {manufacturer}
DATE: Official Demand Notice
RE: RECALL CORRECTIVE ACTION & FINANCIAL RECOVERY — CATALOG #{catalog}

Dear Supplier Recall Coordinator:

Trinity Health System has identified substantial purchase exposure and quarantined inventory across our hospital network for Catalog #{catalog} ({product_description}) subject to active recall actions.

Pursuant to the terms of our Master Supply Agreement and standard GPO commercial warranties, Trinity Health formally demands:

1. RETURN MATERIAL AUTHORIZATION (RMA) ISSUANCE
Immediately issue pre-authorized RMA return paperwork and furnish pre-paid hazardous/freight return shipping waybills for all quarantined inventory across our facilities within forty-eight (48) hours of receipt of this notice.

2. FINANCIAL RESTITUTION & 100% CREDIT MEMO
Process an immediate 100% credit memo in the amount of {claim_formatted} against Trinity Health's master accounts payable balance, covering purchase price, handling fees, and logistical containment costs incurred.

3. SUPPLY CONTINUITY & ALTERNATIVE CONVERSION
Confirm availability of validated, non-recalled alternative lots or bio-equivalent clinical substitutes to prevent procedural interruptions at our acute care sites.

Please confirm receipt and furnish RMA documentation to our Central Recall Coordination Office within 48 business hours.

Sincerely,
Central Supply Chain & Patient Safety Operations
Trinity Health System

[Synthesized by SupplyCopia Ask The Bee Enterprise Sourcing Co-Pilot]"""

        return {"subject": subject, "body": body}

clinical_memo_service = ClinicalMemoService()
