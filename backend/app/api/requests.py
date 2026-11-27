from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import workflow
from app.auth import client_info, current_user
from app.db import get_db
from app.errors import NotFound
from app.models import (
    ApprovalStep,
    Attachment,
    Invoice,
    RequestRevision,
    SpendRequest,
    User,
)
from app.permissions import can_view, request_permissions, visibility_clause
from app.reports import waiting_for
from app.serializers import request_detail, request_summary
from app.storage import get_storage

router = APIRouter(prefix="/api", tags=["requests"])

NON_NULLABLE = {"title", "currency", "amount", "payment_type", "is_confidential"}


class RequestFields(BaseModel):
    title: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=5000)
    supplier: str | None = Field(None, max_length=200)
    category_id: int | None = None
    project_id: int | None = None
    currency: str | None = Field(None, min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    amount: Decimal | None = Field(None, ge=0, le=Decimal("1000000000"), decimal_places=2)
    payment_type: Literal["one_off", "recurring"] | None = None
    billing_period: Literal["monthly", "quarterly", "annually"] | None = None
    term_months: int | None = Field(None, ge=1, le=120)
    start_date: date | None = None
    needed_by: date | None = None
    no_quote_reason: str | None = Field(None, max_length=1000)
    is_confidential: bool | None = None

    def changes(self) -> dict[str, Any]:
        data = self.model_dump(exclude_unset=True)
        return {k: v for k, v in data.items() if not (k in NON_NULLABLE and v is None)}


class AmendBody(RequestFields):
    reason: str = Field(min_length=1, max_length=2000)


class CommentBody(BaseModel):
    comment: str | None = Field(None, max_length=2000)


class RejectBody(BaseModel):
    reason: str = Field(max_length=120)
    comment: str | None = Field(None, max_length=2000)


class ReturnBody(BaseModel):
    comment: str = Field(max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(max_length=2000)


class NoteBody(BaseModel):
    note: str | None = Field(None, max_length=2000)


class NewComment(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class PayBody(BaseModel):
    paid_on: date
    reference: str | None = Field(None, max_length=120)


def summary_options():
    return (
        selectinload(SpendRequest.requester),
        selectinload(SpendRequest.department),
        selectinload(SpendRequest.site),
        selectinload(SpendRequest.category),
        selectinload(SpendRequest.project),
        selectinload(SpendRequest.steps).selectinload(ApprovalStep.approver),
        selectinload(SpendRequest.attachments),
        selectinload(SpendRequest.invoices),
    )


def detail_options():
    return (
        *summary_options(),
        selectinload(SpendRequest.steps).selectinload(ApprovalStep.acted_by),
        selectinload(SpendRequest.steps).selectinload(ApprovalStep.on_behalf_of),
        selectinload(SpendRequest.revisions).selectinload(RequestRevision.created_by),
        selectinload(SpendRequest.attachments).selectinload(Attachment.uploaded_by),
        selectinload(SpendRequest.invoices).selectinload(Invoice.received_by),
        selectinload(SpendRequest.invoices).selectinload(Invoice.paid_by),
        selectinload(SpendRequest.invoices).selectinload(Invoice.queried_by),
        selectinload(SpendRequest.invoices).selectinload(Invoice.voided_by),
        selectinload(SpendRequest.invoices).selectinload(Invoice.attachments),
        selectinload(SpendRequest.comments),
        selectinload(SpendRequest.policy_version),
    )


def load(db: Session, ref: str, user: User) -> SpendRequest:
    req = db.execute(select(SpendRequest).where(SpendRequest.ref == ref.upper()).options(*detail_options())).scalar()
    if req is None or not can_view(db, user, req):
        # Same answer whether it doesn't exist or you can't see it.
        raise NotFound("Request not found.")
    return req


def detail(db: Session, ref: str, user: User) -> dict[str, Any]:
    db.expire_all()
    req = load(db, ref, user)
    return request_detail(db, req, request_permissions(db, user, req))


@router.get("/requests")
def list_requests(
    scope: Literal["all", "mine", "waiting"] = "all",
    status: str | None = None,
    q: str | None = None,
    category_id: int | None = None,
    category_group: str | None = None,
    department_id: int | None = None,
    project_id: int | None = None,
    site_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    stmt = select(SpendRequest).where(visibility_clause(db, user))
    if scope == "mine":
        stmt = stmt.where(SpendRequest.requester_id == user.id)
    elif scope == "waiting":
        ids = [r.id for r in waiting_for(db, user)]
        stmt = stmt.where(SpendRequest.id.in_(ids or [-1]))
    if status:
        stmt = stmt.where(SpendRequest.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if category_id:
        stmt = stmt.where(SpendRequest.category_id == category_id)
    if category_group:
        from app.models import Category

        stmt = stmt.where(SpendRequest.category_id.in_(select(Category.id).where(Category.group == category_group)))
    if department_id:
        stmt = stmt.where(SpendRequest.department_id == department_id)
    if project_id:
        stmt = stmt.where(SpendRequest.project_id == project_id)
    if site_id:
        stmt = stmt.where(SpendRequest.site_id == site_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(SpendRequest.title).like(like),
                func.lower(SpendRequest.ref).like(like),
                func.lower(SpendRequest.supplier).like(like),
                SpendRequest.requester_id.in_(select(User.id).where(func.lower(User.name).like(like))),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(
        stmt.options(*summary_options())
        .order_by(func.coalesce(SpendRequest.submitted_at, SpendRequest.created_at).desc(), SpendRequest.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars()
    return {"items": [request_summary(r) for r in rows], "total": total}


@router.post("/requests/preview")
def preview(body: RequestFields, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workflow.preview_route(db, user, body.changes())


@router.post("/requests", status_code=201)
def create(body: RequestFields, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = workflow.create_draft(db, user, body.changes())
    db.commit()
    return detail(db, req.ref, user)


@router.get("/requests/{ref}")
def get_one(ref: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = load(db, ref, user)
    workflow.mark_viewed(db, user, req, client_info(request))
    db.commit()
    return request_detail(db, req, request_permissions(db, user, req))


@router.patch("/requests/{ref}")
def update(ref: str, body: RequestFields, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.update_draft(db, user, load(db, ref, user), body.changes())
    db.commit()
    return detail(db, ref, user)


@router.delete("/requests/{ref}")
def delete(ref: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.delete_draft(db, user, load(db, ref, user))
    db.commit()
    return {"ok": True}


@router.post("/requests/{ref}/submit")
def submit(ref: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.submit(db, user, load(db, ref, user), client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/approve")
def approve(ref: str, body: CommentBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.approve(db, user, load(db, ref, user), body.comment, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/reject")
def reject(ref: str, body: RejectBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.reject(db, user, load(db, ref, user), body.reason, body.comment, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/return")
def return_(ref: str, body: ReturnBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.return_to_requester(db, user, load(db, ref, user), body.comment, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/withdraw")
def withdraw(ref: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.withdraw(db, user, load(db, ref, user), client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/amend")
def amend(ref: str, body: AmendBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    changes = RequestFields.model_validate(body.model_dump(exclude={"reason"}, exclude_unset=True)).changes()
    _, explanation, needs_reapproval = workflow.amend(db, user, load(db, ref, user), changes, body.reason, client_info(request))
    db.commit()
    return {**detail(db, ref, user), "amendment": {"needs_reapproval": needs_reapproval, "explanation": explanation}}


@router.post("/requests/{ref}/cancel")
def cancel(ref: str, body: ReasonBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.cancel(db, user, load(db, ref, user), body.reason, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/close")
def close(ref: str, body: NoteBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.close(db, user, load(db, ref, user), body.note, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/comments")
def comment(ref: str, body: NewComment, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow.add_comment(db, user, load(db, ref, user), body.body, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/requests/{ref}/attachments")
async def upload(
    ref: str,
    file: UploadFile = File(...),
    kind: Literal["quote", "supporting"] = Form("quote"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = await file.read()
    workflow.add_attachment(db, user, load(db, ref, user), file.filename or "file", data, kind)
    db.commit()
    return detail(db, ref, user)


@router.delete("/requests/{ref}/attachments/{attachment_id}")
def remove_upload(ref: str, attachment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = load(db, ref, user)
    att = next((a for a in req.attachments if a.id == attachment_id), None)
    if att is None:
        raise NotFound("Document not found.")
    workflow.remove_attachment(db, user, att)
    db.commit()
    return detail(db, ref, user)


@router.get("/attachments/{attachment_id}")
def download(attachment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, attachment_id)
    if att is None or not can_view(db, user, att.request):
        raise NotFound("Document not found.")
    data = get_storage().get(att.storage_key)
    inline = att.content_type in ("application/pdf", "image/png", "image/jpeg", "image/webp")
    disposition = "inline" if inline else "attachment"
    safe = att.filename.replace('"', "").encode("ascii", "ignore").decode() or "document"
    return Response(
        content=data,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe}"',
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/requests/{ref}/invoices")
async def record_invoice(
    ref: str,
    request: Request,
    invoice_number: str = Form(..., max_length=80),
    invoice_date: date = Form(...),
    amount: Decimal = Form(..., gt=0),
    currency: str = Form(..., min_length=3, max_length=3),
    supplier: str | None = Form(None, max_length=200),
    notes: str | None = Form(None, max_length=2000),
    override_reason: str | None = Form(None, max_length=2000),
    replaces_invoice_id: int | None = Form(None),
    file: UploadFile | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    req = load(db, ref, user)
    payload = (file.filename or "invoice", await file.read()) if file is not None and file.filename else None
    workflow.record_invoice(
        db,
        user,
        req,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        amount=amount,
        currency=currency,
        supplier=supplier,
        notes=notes,
        override_reason=override_reason,
        file=payload,
        client=client_info(request),
        replaces_invoice_id=replaces_invoice_id,
    )
    db.commit()
    return detail(db, ref, user)


def load_invoice(db: Session, invoice_id: int, user: User) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or not can_view(db, user, inv.request):
        raise HTTPException(404, "Invoice not found.")
    return inv


@router.post("/invoices/{invoice_id}/pay")
def pay(invoice_id: int, body: PayBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = load_invoice(db, invoice_id, user)
    ref = inv.request.ref
    workflow.mark_paid(db, user, inv, body.paid_on, body.reference, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/invoices/{invoice_id}/query")
def query_invoice(invoice_id: int, body: ReasonBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = load_invoice(db, invoice_id, user)
    ref = inv.request.ref
    workflow.query_invoice(db, user, inv, body.reason, client_info(request))
    db.commit()
    return detail(db, ref, user)


@router.post("/invoices/{invoice_id}/accept")
def accept_invoice(invoice_id: int, body: NoteBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = load_invoice(db, invoice_id, user)
    ref = inv.request.ref
    workflow.accept_invoice(db, user, inv, body.note or "", client_info(request))
    db.commit()
    return detail(db, ref, user)
