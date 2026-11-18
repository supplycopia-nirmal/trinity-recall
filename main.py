import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from config import settings
from services.data_service import data_service
from services.action_service import action_service
from services.inventory_service import inventory_service
from services.jira_service import jira_service, LIFECYCLE_STAGES
from services.memo_service import clinical_memo_service
from services.fda_surveillance_service import fda_surveillance_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("trinity_recall_hub")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Streamlined Recall Intelligence, Hospital Facility Exposure, and Operational Action Workflows for Trinity Health"
)

# Sessions for login state
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    max_age=14 * 86400,
    same_site="lax"
)

# Templates & Static Files
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

class GenerateClinicalMemoRequest(BaseModel):
    catalog: str
    facility: Optional[str] = "FACILITY-150"
    facility_display: Optional[str] = "Trinity Health Ann Arbor Hospital (MI)"
    product_description: Optional[str] = ""
    manufacturer: Optional[str] = ""
    risk_class: Optional[str] = "Class II"
    recall_reason: Optional[str] = ""
    estimated_units: Optional[float] = 0

class GenerateSupplierDemandRequest(BaseModel):
    manufacturer: str
    catalog: str
    product_description: Optional[str] = ""
    claim_amount: Optional[float] = 5000.00
    action_type: Optional[str] = "RMA Return & 100% Credit Claim"

class QuarantineLotRequest(BaseModel):
    facility: str
    catalog: str
    lot_number: str
    status: str  # "RECALL_QUARANTINED" or "AVAILABLE"

class FacilityNotifyRequest(BaseModel):
    facility: str
    facility_display: str
    catalog: str
    product_description: str
    manufacturer: str
    recipient: str
    subject: str
    message: str
    risk_class: Optional[str] = "Class II"
    sync_jira: Optional[bool] = True

class InventoryNotifyRequest(BaseModel):
    facility: str
    facility_display: str
    catalog: str
    product_description: str
    manufacturer: str
    recipient: str
    subject: str
    message: str
    quarantine_location: Optional[str] = "Quarantine Bay 1 - Red Bin"
    estimated_units: Optional[float] = 0
    sync_jira: Optional[bool] = True

class OrderManagementNotifyRequest(BaseModel):
    facility: str
    facility_display: str
    catalog: str
    product_description: str
    manufacturer: str
    recipient: str
    subject: str
    message: str
    po_number: Optional[str] = None
    total_spend: Optional[float] = 0
    sync_jira: Optional[bool] = True

class SupplierMessageRequest(BaseModel):
    manufacturer: str
    catalog: str
    product_description: str
    supplier_action_type: str
    recipient: str
    subject: str
    message: str
    claim_amount: Optional[float] = 0
    facility: Optional[str] = "SYSTEM-WIDE"
    sync_jira: Optional[bool] = True

class CreateJiraCaseRequest(BaseModel):
    catalog: str
    product_description: str
    manufacturer: str
    risk_class: Optional[str] = "Class II"
    facility: Optional[str] = "All Impacted Sites"
    recall_reason: Optional[str] = "FDA Medical Device / Supply Recall"
    lifecycle_step: Optional[str] = "Step 1: Receive and Register"
    accountable_role: Optional[str] = "Central Recall Coordinator"
    action_type: Optional[str] = "RECALL_CASE"
    summary_override: Optional[str] = None
    priority: Optional[str] = "High"
    duedate: Optional[str] = None
    assignee_id: Optional[str] = None
    custom_description: Optional[str] = None
    checklist: Optional[List[str]] = None

class AddJiraCommentRequest(BaseModel):
    comment: str

class TransitionJiraStageRequest(BaseModel):
    target_step: int

class LoginRequest(BaseModel):
    username: str
    password: str

# HTML Routes
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    user = request.session.get("user")
    if not user:
        # Default session user for demo convenience if not set
        request.session["user"] = {
            "name": "Sarah Jenkins, RN, CMRP",
            "role": "Director of Supply Chain & Patient Safety",
            "health_system": "Trinity Health",
            "email": settings.DEMO_USER
        }
        user = request.session.get("user")
        
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "project_name": settings.PROJECT_NAME
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "default_user": settings.DEMO_USER,
        "default_pass": settings.DEMO_PASS
    })

@app.post("/api/auth/login")
async def login_submit(request: Request, payload: LoginRequest):
    # Friendly demo authentication
    if payload.username and payload.password:
        request.session["user"] = {
            "name": "Sarah Jenkins, RN, CMRP",
            "role": "Director of Supply Chain & Patient Safety",
            "health_system": "Trinity Health",
            "email": payload.username
        }
        return {"status": "ok", "redirect": "/"}
    raise HTTPException(status_code=400, detail="Invalid credentials")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

# REST API Endpoints
@app.get("/api/kpi")
async def get_kpis():
    """Returns Executive KPIs and Action Summary for Trinity Health."""
    kpis = data_service.get_kpis()
    action_metrics = action_service.get_summary_metrics()
    return {
        "data_kpis": kpis,
        "action_metrics": action_metrics
    }

@app.get("/api/recalls")
async def get_recalls(
    query: Optional[str] = Query(None, description="Search term across name, cat#, mfg, and FDA recall reason"),
    fda_class: Optional[str] = Query("ALL", description="Filter by FDA Class: ALL, Class I, Class II, Class III"),
    action_filter: Optional[str] = Query("ALL", description="Filter by required action: ALL, PULL, STOP"),
    facility: Optional[str] = Query("ALL", description="Filter by specific hospital facility"),
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=5, le=100)
):
    """Returns paginated, filtered recalled products."""
    results = data_service.get_recalls(
        query=query,
        fda_class=fda_class,
        action_filter=action_filter,
        facility=facility,
        page=page,
        page_size=page_size
    )
    return results

@app.get("/api/recalls/{catalog}")
async def get_product_detail(catalog: str):
    """Returns full details for a recalled product."""
    detail = data_service.get_product_detail(catalog)
    if not detail:
        raise HTTPException(status_code=404, detail="Recalled product not found")
    return detail

@app.get("/api/catalog/{catalog}/dossier")
async def get_catalog_dossier(catalog: str, facility: str = Query("FACILITY-150")):
    """Returns full Catalog Intelligence Dossier with FDA details and physical lot tracking."""
    dossier = data_service.get_catalog_dossier(catalog=catalog, facility=facility)
    if not dossier:
        raise HTTPException(status_code=404, detail="Catalog dossier not found")
    return dossier

@app.get("/api/inventory/item/{catalog}")
async def get_inventory_item(catalog: str, facility: str = Query("FACILITY-150")):
    """Returns simulated lot-level details, physical bins, and on-hand substitutes."""
    item = data_service.get_product_detail(catalog) or {}
    return inventory_service.simulate_inventory(
        catalog=catalog,
        facility=facility,
        product_description=item.get("product_description", ""),
        manufacturer=item.get("manufacturer", ""),
        fda_classification=item.get("fda_classification", "Class II")
    )

@app.post("/api/inventory/quarantine-lot")
async def update_lot_quarantine(payload: QuarantineLotRequest):
    """Updates physical quarantine status of an item's production lot (Hold / Release)."""
    success = inventory_service.update_lot_quarantine_status(
        facility=payload.facility,
        catalog=payload.catalog,
        lot_number=payload.lot_number,
        new_status=payload.status
    )
    # Log in audit trail
    action_service._actions.insert(0, {
        "id": f"ACT-{len(action_service._actions) + 1001}",
        "action_type": "INVENTORY_PULL",
        "type_label": f"Lot {'Quarantine Hold' if payload.status == 'RECALL_QUARANTINED' else 'Stock Release'}",
        "status": "Verified",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "facility": payload.facility,
        "facility_display": f"Trinity Health Hospital [{payload.facility}]",
        "catalog": payload.catalog,
        "product_description": f"Lot {payload.lot_number} status updated to {payload.status}",
        "manufacturer": "Materials Management Terminal",
        "recipient": f"materials-dock@{payload.facility.lower()}.trinity-health.org",
        "subject": f"LOT STATUS MUTATION: {payload.lot_number} -> {payload.status}",
        "message": f"Physical lot quarantine status changed for {payload.catalog} at {payload.facility}.",
        "details": {"lot_number": payload.lot_number, "status": payload.status}
    })
    action_service._save_actions()
    return {"success": success, "facility": payload.facility, "catalog": payload.catalog, "lot_number": payload.lot_number, "status": payload.status}

@app.get("/api/dashboard/analytics")
async def get_dashboard_analytics(
    po_date_from: Optional[str] = Query(None),
    po_date_to: Optional[str] = Query(None),
    recall_date_from: Optional[str] = Query(None),
    recall_date_to: Optional[str] = Query(None),
    action_needed: Optional[str] = Query(None),
    risk_score: Optional[str] = Query(None),
    po_number: Optional[str] = Query(None),
    facility: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    catalog: Optional[str] = Query(None)
):
    """Returns analytics matching the screenshot: KPIs, Timeline stacked chart, Action doughnut, Mfg bar, Risk bar with optional filters."""
    analytics = data_service.get_dashboard_analytics(
        po_date_from=po_date_from,
        po_date_to=po_date_to,
        recall_date_from=recall_date_from,
        recall_date_to=recall_date_to,
        action_needed=action_needed,
        risk_score=risk_score,
        po_number=po_number,
        facility=facility,
        manufacturer=manufacturer,
        catalog=catalog
    )
    # Populate OPEN TASKS KPI with live count of open Jira issues in TRM space
    try:
        jira_open_count = jira_service.get_open_issues_count()
        analytics["open_tasks"] = jira_open_count
    except Exception as e:
        logger.warning(f"Failed to fetch live Jira open issues count: {e}")
    return analytics

@app.get("/api/dashboard/alerts")
async def get_dashboard_alerts(
    po_date_from: Optional[str] = Query(None),
    po_date_to: Optional[str] = Query(None),
    recall_date_from: Optional[str] = Query(None),
    recall_date_to: Optional[str] = Query(None),
    action_needed: Optional[str] = Query(None),
    risk_score: Optional[str] = Query(None),
    po_number: Optional[str] = Query(None),
    facility: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    catalog: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=5, le=100)
):
    """Returns detailed PO alert records for the screenshot table."""
    return data_service.get_dashboard_alerts_table(
        po_date_from=po_date_from,
        po_date_to=po_date_to,
        recall_date_from=recall_date_from,
        recall_date_to=recall_date_to,
        action_needed=action_needed,
        risk_score=risk_score,
        po_number=po_number,
        facility=facility,
        manufacturer=manufacturer,
        catalog=catalog,
        page=page,
        page_size=page_size
    )

@app.get("/api/recalls/{catalog}/facilities")
async def get_facilities_for_product(catalog: str):
    """Returns which hospital facilities bought this recalled product."""
    facilities = data_service.get_facilities_for_product(catalog)
    return {"catalog": catalog, "facilities": facilities, "total_facilities": len(facilities)}

@app.get("/api/recalls/{catalog}/facilities/{facility}/pos")
async def get_pos_for_facility(catalog: str, facility: str):
    """Returns individual PO line items for a product and facility."""
    pos = data_service.get_purchase_orders_for_facility_product(catalog, facility)
    return {"catalog": catalog, "facility": facility, "purchase_orders": pos, "total_pos": len(pos)}

@app.get("/api/facilities")
async def get_facilities_list():
    """Returns dropdown list of all hospital facilities."""
    return data_service.get_facilities_list()

@app.get("/api/search")
async def search_all(q: str = Query(..., min_length=1)):
    """Deep search across products, facilities, and FDA recall reasons."""
    results = data_service.get_recalls(query=q, page=1, page_size=25)
    return results

# Action Dispatch Endpoints
@app.post("/api/actions/notify-facility")
async def notify_facility(payload: FacilityNotifyRequest):
    """Dispatches a clinical safety notice to hospital facility departments."""
    result = action_service.notify_facility(
        facility=payload.facility,
        facility_display=payload.facility_display,
        catalog=payload.catalog,
        product_description=payload.product_description,
        manufacturer=payload.manufacturer,
        recipient=payload.recipient,
        subject=payload.subject,
        message=payload.message,
        risk_class=payload.risk_class or "Class II",
        sync_jira=payload.sync_jira if payload.sync_jira is not None else True
    )
    return {"status": "success", "action": result}

@app.post("/api/actions/notify-inventory")
async def notify_inventory(payload: InventoryNotifyRequest):
    """Dispatches a physical stock pull & quarantine work order."""
    result = action_service.notify_inventory(
        facility=payload.facility,
        facility_display=payload.facility_display,
        catalog=payload.catalog,
        product_description=payload.product_description,
        manufacturer=payload.manufacturer,
        recipient=payload.recipient,
        subject=payload.subject,
        message=payload.message,
        quarantine_location=payload.quarantine_location or "Quarantine Bay 1 - Red Bin",
        estimated_units=payload.estimated_units or 0,
        sync_jira=payload.sync_jira if payload.sync_jira is not None else True
    )
    return {"status": "success", "action": result}

@app.post("/api/actions/notify-order-management")
async def notify_order_management(payload: OrderManagementNotifyRequest):
    """Dispatches a PO stop & cancellation notice."""
    result = action_service.notify_order_management(
        facility=payload.facility,
        facility_display=payload.facility_display,
        catalog=payload.catalog,
        product_description=payload.product_description,
        manufacturer=payload.manufacturer,
        recipient=payload.recipient,
        subject=payload.subject,
        message=payload.message,
        po_number=payload.po_number,
        total_spend=payload.total_spend or 0,
        sync_jira=payload.sync_jira if payload.sync_jira is not None else True
    )
    return {"status": "success", "action": result}

@app.post("/api/actions/supplier-message")
async def send_supplier_message(payload: SupplierMessageRequest):
    """Dispatches an official supplier inquiry or RMA/credit demand."""
    result = action_service.send_supplier_message(
        manufacturer=payload.manufacturer,
        catalog=payload.catalog,
        product_description=payload.product_description,
        supplier_action_type=payload.supplier_action_type,
        recipient=payload.recipient,
        subject=payload.subject,
        message=payload.message,
        claim_amount=payload.claim_amount or 0,
        facility=payload.facility or "SYSTEM-WIDE",
        sync_jira=payload.sync_jira if payload.sync_jira is not None else True
    )
    return {"status": "success", "action": result}

@app.get("/api/actions")
async def get_actions_log(action_type: Optional[str] = "ALL", limit: int = 100):
    """Returns the live audit trail of dispatched notifications and actions."""
    actions = action_service.get_actions(action_type=action_type, limit=limit)
    return {"actions": actions, "count": len(actions)}

@app.post("/api/memo/generate")
async def generate_clinical_memo(payload: GenerateClinicalMemoRequest):
    """
    Generates a high-fidelity Clinical Safety & Recall Memo powered by OpenAI LLM
    or rich clinical safety expert engine with specific bedside guidance.
    """
    memo = clinical_memo_service.generate_clinical_memo(
        catalog=payload.catalog,
        facility=payload.facility or "FACILITY-150",
        facility_display=payload.facility_display or "Trinity Health Hospital Site",
        product_description=payload.product_description or "Medical Device / Clinical Supply",
        manufacturer=payload.manufacturer or "Medical Supply Manufacturer",
        risk_class=payload.risk_class or "Class II",
        recall_reason=payload.recall_reason or "FDA recall notice issued.",
        estimated_units=payload.estimated_units or 0
    )
    return {"status": "success", "memo": memo}

@app.post("/api/supplier/draft-demand")
async def generate_supplier_demand(payload: GenerateSupplierDemandRequest):
    """
    Generates an executive supplier demand and RMA claim message powered by Ask The Bee AI.
    """
    letter = clinical_memo_service.generate_supplier_demand(
        manufacturer=payload.manufacturer,
        catalog=payload.catalog,
        product_description=payload.product_description or "Medical Device / Clinical Supply",
        claim_amount=payload.claim_amount or 5000.0,
        action_type=payload.action_type or "RMA Return & 100% Credit Claim"
    )
    return {"status": "success", "letter": letter}

# Jira Workflow Management Endpoints
@app.get("/api/jira/status")
async def get_jira_status():
    """Returns connection and board metadata for Jira TRM space."""
    return jira_service.test_connection()

@app.get("/api/jira/metadata")
async def get_jira_metadata():
    """Returns assignable users and priorities for creating customized Jira tickets."""
    users = jira_service.get_assignable_users()
    priorities = jira_service.get_priorities()
    return {"users": users, "priorities": priorities}

@app.get("/api/jira/issues")
async def get_jira_issues(limit: int = 50):
    """Returns live tasks and issues currently in Jira project TRM."""
    issues = jira_service.get_project_issues(limit=limit)
    return {"issues": issues, "count": len(issues)}

@app.post("/api/jira/case")
async def create_jira_recall_case(payload: CreateJiraCaseRequest):
    """Creates an official Recall Task in Jira project TRM according to the 8-stage operating model."""
    result = jira_service.create_recall_case(
        catalog=payload.catalog,
        product_description=payload.product_description,
        manufacturer=payload.manufacturer,
        risk_class=payload.risk_class or "Class II",
        facility=payload.facility or "All Impacted Sites",
        recall_reason=payload.recall_reason or "FDA Medical Device / Supply Recall",
        lifecycle_step=payload.lifecycle_step or "Step 1: Receive and Register",
        accountable_role=payload.accountable_role or "Central Recall Coordinator",
        action_type=payload.action_type or "RECALL_CASE",
        summary_override=payload.summary_override,
        priority=payload.priority,
        duedate=payload.duedate,
        assignee_id=payload.assignee_id,
        custom_description=payload.custom_description,
        checklist=payload.checklist
    )
    return result

@app.get("/api/orders/{po_number}")
async def get_purchase_order_details(po_number: str):
    """Returns line item detail for an interactive purchase order modal."""
    details = data_service.get_purchase_order_details(po_number)
    if not details:
        raise HTTPException(status_code=404, detail=f"Purchase order {po_number} not found.")
    return details

@app.get("/api/suppliers")
async def get_suppliers(
    q: Optional[str] = "",
    fda_class: Optional[str] = "",
    sort_by: Optional[str] = "spend_desc"
):
    """Returns comprehensive directory of all suppliers with impact metrics."""
    suppliers = data_service.get_all_suppliers(
        query=q or "",
        fda_class=fda_class or "",
        sort_by=sort_by or "spend_desc"
    )
    return {"suppliers": suppliers, "count": len(suppliers)}

@app.get("/api/jira/lifecycle-stages")
async def get_jira_lifecycle_stages():
    """Returns the 8 standard operating model stages for health system recall workflow."""
    return {"stages": LIFECYCLE_STAGES}

@app.post("/api/jira/issues/{issue_key}/comment")
async def add_jira_comment(issue_key: str, payload: AddJiraCommentRequest):
    """Appends an operational audit comment to a Jira issue."""
    result = jira_service.add_issue_comment(issue_key, payload.comment)
    return result

@app.post("/api/jira/issues/{issue_key}/transition")
async def transition_jira_stage(issue_key: str, payload: TransitionJiraStageRequest):
    """Advances or updates the 8-stage operating model state of a Jira recall issue."""
    result = jira_service.transition_issue_stage(issue_key, payload.target_step)
    return result

@app.get("/api/fda/medwatch")
async def get_fda_medwatch_grievances(catalog: Optional[str] = Query(None)):
    """Returns FDA MedWatch & MAUDE user grievances, quality issues, packaging defects."""
    grievances = fda_surveillance_service.get_medwatch_grievances(catalog=catalog)
    return {
        "status": "SUCCESS",
        "count": len(grievances),
        "catalog_filter": catalog,
        "grievances": grievances
    }

@app.post("/api/fda/medwatch/sync")
async def sync_fda_medwatch_feed():
    """Polls openFDA device events (MAUDE / MedWatch) API for recent user reports."""
    result = fda_surveillance_service.sync_medwatch_feed()
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
