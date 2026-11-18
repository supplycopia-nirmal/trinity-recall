import base64
import json
import logging
import uuid
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

# Standard 8-Stage Operating Model from Health System Recall Management Workflow doc
LIFECYCLE_STAGES = [
    {"step": 1, "name": "Receive and Register", "owner": "Central Recall Coordinator", "color": "#0072B2"},
    {"step": 2, "name": "Assess and Assign", "owner": "Coordinator & Product Lead", "color": "#E69F00"},
    {"step": 3, "name": "Locate Products", "owner": "Supply Chain / Pharmacy Lead", "color": "#56B4E9"},
    {"step": 4, "name": "Contain Exposure", "owner": "Materials & Department Leads", "color": "#D55E00"},
    {"step": 5, "name": "Identify Patients", "owner": "Informatics & Procedural Teams", "color": "#CC79A7"},
    {"step": 6, "name": "Manage Follow-up", "owner": "Treating Clinician / Service Owner", "color": "#009E73"},
    {"step": 7, "name": "Correct or Dispose", "owner": "Vendor & Supply Chain Lead", "color": "#F0E442"},
    {"step": 8, "name": "Verify and Close", "owner": "Quality Reviewer & Safety Officer", "color": "#1E293B"}
]

class JiraService:
    """
    Integrates Trinity Health Recall Management Platform with Atlassian Jira Cloud (Project: TRM).
    Aligns recall incidents with the 8-Stage Hospital Operating Model.
    """

    def __init__(self):
        self.base_url = settings.JIRA_BASE_URL.rstrip("/")
        self.project_key = settings.JIRA_PROJECT_KEY
        self.board_id = settings.JIRA_BOARD_ID
        self.email = settings.JIRA_USER_EMAIL
        self.token = settings.JIRA_API_TOKEN
        self._auth_header = None
        if self.email and self.token:
            auth_str = f"{self.email}:{self.token}"
            self._auth_header = f"Basic {base64.b64encode(auth_str.encode()).decode()}"

    def is_configured(self) -> bool:
        return bool(self._auth_header and self.project_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._auth_header or "",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def test_connection(self) -> Dict[str, Any]:
        """Tests Jira connection and returns project and board metadata."""
        if not self.is_configured():
            return {"status": "unconfigured", "message": "Jira API credentials not configured in .env"}

        try:
            url = f"{self.base_url}/rest/api/3/myself"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                user_data = json.loads(resp.read().decode())
                return {
                    "status": "connected",
                    "user_name": user_data.get("displayName"),
                    "user_email": user_data.get("emailAddress"),
                    "project_key": self.project_key,
                    "board_id": self.board_id,
                    "board_url": f"{self.base_url}/jira/software/projects/{self.project_key}/boards/{self.board_id}"
                }
        except urllib.error.HTTPError as e:
            return {"status": "error", "code": e.code, "message": e.read().decode()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def upload_attachment(self, issue_key: str, filename: str, file_bytes: bytes, content_type: str = "text/csv") -> Optional[Dict[str, Any]]:
        """
        Uploads a supporting document attachment (e.g. .csv of affected lots) to a Jira issue.
        """
        if not self.is_configured():
            return None

        boundary = f"----JiraBoundary{uuid.uuid4().hex}"
        body_parts = [
            f"--{boundary}".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n".encode("utf-8"),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode("utf-8")
        ]
        body = b"\r\n".join(body_parts[:-1]) + body_parts[-1]

        headers = {
            "Authorization": self._auth_header or "",
            "X-Atlassian-Token": "no-check",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }

        try:
            url = f"{self.base_url}/rest/api/3/issue/{issue_key}/attachments"
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode())
                if isinstance(res, list) and len(res) > 0:
                    att = res[0]
                    logger.info(f"Attached {filename} ({att.get('size')} bytes) to {issue_key}")
                    return att
        except Exception as e:
            logger.error(f"Failed to attach {filename} to {issue_key}: {e}")
    def get_assignable_users(self) -> List[Dict[str, Any]]:
        """Returns assignable users for TRM project in Jira Cloud."""
        if not self.is_configured():
            return []
        try:
            url = f"{self.base_url}/rest/api/3/user/assignable/search?project={self.project_key}"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                users = json.loads(resp.read().decode())
                return [
                    {
                        "accountId": u.get("accountId"),
                        "displayName": u.get("displayName"),
                        "emailAddress": u.get("emailAddress", ""),
                        "avatarUrl": u.get("avatarUrls", {}).get("24x24", "")
                    }
                    for u in users if u.get("accountType") != "app" or "Agent" in u.get("displayName", "")
                ]
        except Exception as e:
            logger.error(f"Failed to fetch assignable users: {e}")
            return []

    def get_priorities(self) -> List[Dict[str, Any]]:
        """Returns standard Jira issue priorities."""
        if not self.is_configured():
            return []
        try:
            url = f"{self.base_url}/rest/api/3/priority"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"Failed to fetch Jira priorities: {e}")
            return [
                {"id": "1", "name": "Highest"},
                {"id": "2", "name": "High"},
                {"id": "3", "name": "Medium"},
                {"id": "4", "name": "Low"},
                {"id": "5", "name": "Lowest"}
            ]

    def create_recall_case(
        self,
        catalog: str,
        product_description: str,
        manufacturer: str,
        risk_class: str = "Class II",
        facility: str = "All Impacted Sites",
        recall_reason: str = "FDA Medical Device / Supply Recall",
        lifecycle_step: str = "Step 1: Receive and Register",
        accountable_role: str = "Central Recall Coordinator",
        action_type: str = "RECALL_CASE",
        summary_override: Optional[str] = None,
        priority: Optional[str] = None,
        duedate: Optional[str] = None,
        assignee_id: Optional[str] = None,
        custom_description: Optional[str] = None,
        checklist: Optional[List[str]] = None,
        extra_details: Optional[Dict[str, Any]] = None,
        csv_attachment_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Creates an official Jira Task / Recall Case in TRM space with rich operational details,
        assignee, priority, due date, custom description, checklist, and automatic attachments.
        """
        if not self.is_configured():
            logger.warning("Jira not configured. Skipping ticket creation.")
            return {"success": False, "error": "Jira credentials missing"}

        summary = summary_override or f"[{risk_class}] Recall Incident: {catalog} - {manufacturer} ({facility})"
        if len(summary) > 250:
            summary = summary[:247] + "..."

        extra = extra_details or {}
        on_hand = extra.get("estimated_units", 0)
        quarantine_loc = extra.get("quarantine_location", "Designated Quarantine Bay 1 - Red Bin")
        po_number = extra.get("po_number", "All In-Flight / Open POs")
        action_msg = extra.get("directive_message", "")

        # Format comprehensive ADF (Atlassian Document Format) description
        desc_content = [
            # Header Title
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Trinity Health System - Official Recall Case Record"}]
            },
            # Core Metadata Panel / Box
            {
                "type": "panel",
                "attrs": {"panelType": "error" if "I" in risk_class else "warning"},
                "content": [{
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"MANDATORY CLINICAL DIRECTIVE: FDA {risk_class} ALERT", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": f"\nTarget Facility: {facility} | Catalog #: {catalog} | Manufacturer: {manufacturer}"}
                    ]
                }]
            },
            # Section 1: Product Specifications
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "1. Incident & Product Specifications"}]
            },
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Product Catalog #: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(catalog)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Item Description: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(product_description)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Manufacturer: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(manufacturer)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "FDA Regulatory Classification: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(risk_class)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Health System Facility Impact: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(facility)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Operating Model Stage: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(lifecycle_step)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Primary Accountable Role: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(accountable_role)}]}]}
                ]
            },
            # Section 2: Clinical Hazard
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "2. FDA Recall Hazard & Clinical Failure Mechanism"}]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": str(recall_reason)}]
            },
            # Section 3: Supply Chain & Physical Quarantine Parameters
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "3. Hospital Containment & Physical Quarantine Parameters"}]
            },
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Estimated Physical Exposure: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": f"{on_hand} Units across Clinical Units and Storerooms"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Designated Holding Location: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": str(quarantine_loc)}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Purchase Order Hold: ", "marks": [{"type": "strong"}]}, {"type": "text", "text": f"PO {po_number} - EDI 850 transmissions suspended and dock receiving blocked."}]}]}
                ]
            }
        ]

        # If user entered a custom description or remarks, highlight it prominently
        if custom_description and custom_description.strip():
            desc_content.insert(2, {
                "type": "panel",
                "attrs": {"panelType": "info"},
                "content": [{
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "COORDINATOR ASSESSMENT & OPERATIONAL NOTES:\n", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": custom_description.strip()}
                    ]
                }]
            })

        # If custom clinical directive message provided, append it
        if action_msg:
            desc_content.extend([
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "4. Dispatched Operational Directives & Instructions"}]
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": str(action_msg)}]
                }
            ])

        # If operational checklist items provided, render as action checklist
        if checklist and len(checklist) > 0:
            clean_checks = [c.strip() for c in checklist if c.strip()]
            if clean_checks:
                desc_content.extend([
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Operational Task Checklist"}]
                    },
                    {
                        "type": "taskList",
                        "attrs": {"localId": "recall-checklist-001"},
                        "content": [
                            {
                                "type": "taskItem",
                                "attrs": {"localId": f"check-{i}", "state": "TODO"},
                                "content": [{"type": "text", "text": c}]
                            }
                            for i, c in enumerate(clean_checks)
                        ]
                    }
                ])

        # Completion protocol note
        desc_content.extend([
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "5. Compliance & Completion Evidence Protocol"}]
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Per Trinity Health Recall Policy, assignees must upload quarantine receipts, dock stop signoffs, or clinician encounter logs before advancing this issue to Step 8: Verify & Close."}
                ]
            }
        ])

        clean_step = lifecycle_step.replace(":", "").replace(" ", "_").replace("&", "and")
        clean_role = accountable_role.replace(" ", "_").replace("/", "_").replace("&", "and")

        fields_data: Dict[str, Any] = {
            "project": {"key": self.project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": desc_content
            },
            "issuetype": {"name": "Task"},
            "labels": [
                "TrinityRecallHub",
                risk_class.replace(" ", "_"),
                action_type.replace(" ", "_"),
                clean_step,
                f"Role_{clean_role}"
            ]
        }

        # Add Priority if specified
        if priority:
            fields_data["priority"] = {"name": priority}

        # Add Due Date if specified (YYYY-MM-DD)
        if duedate:
            fields_data["duedate"] = duedate

        # Add Assignee if specified
        if assignee_id:
            fields_data["assignee"] = {"accountId": assignee_id}

        payload = {"fields": fields_data}

        try:
            url = f"{self.base_url}/rest/api/3/issue"
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=self._headers())
            with urllib.request.urlopen(req, timeout=12) as resp:
                res = json.loads(resp.read().decode())
                issue_key = res.get("key")
                issue_url = f"{self.base_url}/browse/{issue_key}"
                logger.info(f"Created Jira issue {issue_key} for catalog {catalog}")

                # Automatically upload CSV attachment if provided
                attachment_info = None
                if csv_attachment_data and issue_key:
                    fname = csv_attachment_data.get("filename", f"affected_lots_{catalog}.csv")
                    fbytes = csv_attachment_data.get("bytes", b"")
                    if fbytes:
                        attachment_info = self.upload_attachment(issue_key, fname, fbytes)

                return {
                    "success": True,
                    "key": issue_key,
                    "id": res.get("id"),
                    "url": issue_url,
                    "attachment": attachment_info
                }
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode()
            logger.error(f"Jira API error ({e.code}): {err_msg}")
            return {"success": False, "error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            logger.error(f"Exception creating Jira issue: {e}")
            return {"success": False, "error": str(e)}
            err_msg = e.read().decode()
            logger.error(f"Jira API error ({e.code}): {err_msg}")
            return {"success": False, "error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            logger.error(f"Exception creating Jira issue: {e}")
            return {"success": False, "error": str(e)}

    def get_project_issues(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetches live Jira tasks in project TRM.
        """
        if not self.is_configured():
            return []

        # Try API v3 JQL search
        url = f"{self.base_url}/rest/api/3/search/jql"
        payload = {
            "jql": f"project = {self.project_key} ORDER BY created DESC",
            "maxResults": limit,
            "fields": ["summary", "status", "created", "updated", "assignee", "labels", "priority"]
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=self._headers())
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                issues = data.get("issues", [])
                formatted = []
                for iss in issues:
                    f = iss.get("fields", {})
                    labels = f.get("labels", [])
                    
                    # Resolve operating model step from labels or status
                    step_num = 1
                    step_name = "Step 1: Receive & Register"
                    for l in labels:
                        if l.startswith("Step_"):
                            for s in LIFECYCLE_STAGES:
                                if f"Step_{s['step']}_" in l or f"Step_{s['step']}" == l:
                                    step_num = s["step"]
                                    step_name = f"Step {s['step']}: {s['name']}"
                                    break

                    formatted.append({
                        "key": iss.get("key"),
                        "id": iss.get("id"),
                        "summary": f.get("summary", ""),
                        "status": f.get("status", {}).get("name", "To Do"),
                        "status_category": f.get("status", {}).get("statusCategory", {}).get("name", "To Do"),
                        "step_number": step_num,
                        "step_name": step_name,
                        "created": f.get("created", "")[:19].replace("T", " "),
                        "updated": f.get("updated", "")[:19].replace("T", " "),
                        "assignee": f.get("assignee", {}).get("displayName") if f.get("assignee") else "Unassigned",
                        "labels": labels,
                        "priority": f.get("priority", {}).get("name", "Medium"),
                        "url": f"{self.base_url}/browse/{iss.get('key')}"
                    })
                return formatted
        except Exception as e:
            logger.error(f"Error fetching Jira issues: {e}")
            return []

    def get_open_issues_count(self) -> int:
        """
        Returns the real-time count of active/open Jira issues (excluding Done/Closed).
        """
        if not self.is_configured():
            return 0
        url = f"{self.base_url}/rest/api/3/search/jql"
        payload = {
            "jql": f"project = {self.project_key} AND statusCategory != Done",
            "maxResults": 100,
            "fields": ["id", "status"]
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=self._headers())
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                return len(data.get("issues", []))
        except Exception as e:
            logger.error(f"Error fetching Jira open issues count: {e}")
            return 0

    def transition_issue_stage(self, issue_key: str, target_step: int) -> Dict[str, Any]:
        """
        Advances or moves an issue across the 8-stage operating model.
        Updates labels and performs corresponding Kanban transition if applicable.
        """
        if not self.is_configured():
            return {"success": False, "error": "Jira not configured"}

        target_stage = next((s for s in LIFECYCLE_STAGES if s["step"] == target_step), None)
        if not target_stage:
            return {"success": False, "error": f"Invalid step {target_step}"}

        # 1. First fetch current labels
        current_labels = []
        try:
            url_get = f"{self.base_url}/rest/api/3/issue/{issue_key}?fields=labels"
            req_get = urllib.request.Request(url_get, headers=self._headers())
            with urllib.request.urlopen(req_get, timeout=8) as r:
                curr = json.loads(r.read().decode())
                current_labels = curr.get("fields", {}).get("labels", [])
        except Exception as e:
            logger.warning(f"Could not get current labels for {issue_key}: {e}")

        # Filter out old Step_ labels
        new_labels = [l for l in current_labels if not l.startswith("Step_")]
        clean_step_label = f"Step_{target_stage['step']}_{target_stage['name'].replace(' ', '_').replace('&', 'and')}"
        new_labels.append(clean_step_label)

        # 2. Update issue labels
        try:
            url_put = f"{self.base_url}/rest/api/3/issue/{issue_key}"
            payload_put = {"fields": {"labels": new_labels}}
            req_put = urllib.request.Request(url_put, data=json.dumps(payload_put).encode("utf-8"), headers=self._headers(), method="PUT")
            with urllib.request.urlopen(req_put, timeout=8) as r:
                pass
        except Exception as e:
            logger.error(f"Error updating labels on {issue_key}: {e}")

        # 3. Transition status on Kanban board:
        # Step 1 -> To Do (11)
        # Steps 2-7 -> In Progress (21)
        # Step 8 -> Done (41)
        target_trans_id = "11" if target_step == 1 else ("41" if target_step == 8 else "21")
        try:
            url_trans = f"{self.base_url}/rest/api/3/issue/{issue_key}/transitions"
            payload_trans = {"transition": {"id": target_trans_id}}
            req_trans = urllib.request.Request(url_trans, data=json.dumps(payload_trans).encode("utf-8"), headers=self._headers())
            with urllib.request.urlopen(req_trans, timeout=8) as r:
                pass
        except Exception as e:
            logger.info(f"Transition notice for {issue_key}: {e}")

        # 4. Add audit comment
        self.add_issue_comment(
            issue_key,
            f"RECALL WORKFLOW UPDATE: Advanced to Step {target_stage['step']}: {target_stage['name']}. Accountable Role: {target_stage['owner']}."
        )

        return {
            "success": True,
            "key": issue_key,
            "step": target_stage["step"],
            "stage_name": target_stage["name"],
            "owner": target_stage["owner"]
        }

    def add_issue_comment(self, issue_key: str, comment_text: str) -> bool:
        """Adds an operational audit comment to a Jira issue."""
        if not self.is_configured():
            return False

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text}]
                }]
            }
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in [200, 201]
        except Exception as e:
            logger.error(f"Error adding comment to {issue_key}: {e}")
            return False

jira_service = JiraService()
