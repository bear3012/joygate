from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from joygate.routes.incidents import _validate_optional_str, _validate_required_str

router = APIRouter()

MAX_TARGET_URL_LEN = 2048


class WebhookSubscriptionCreateIn(BaseModel):
    target_url: str
    event_types: list[str]
    secret: Optional[str] = None
    is_enabled: Optional[bool] = None


class WebhookSubscriptionOut(BaseModel):
    subscription_id: str
    target_url: str
    event_types: list[str]
    is_enabled: bool
    created_at: str


class WebhookSubscriptionListOut(BaseModel):
    subscriptions: list[WebhookSubscriptionOut]


class WebhookDeliveryOut(BaseModel):
    delivery_id: str
    event_id: str
    event_type: str
    subscription_id: str
    target_url: str
    delivery_status: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    created_at: str
    updated_at: str
    delivered_at: str | None


class WebhookDeliveryListOut(BaseModel):
    deliveries: list[WebhookDeliveryOut]


@router.post("/v1/webhooks/subscriptions", response_model=WebhookSubscriptionOut)
def v1_webhooks_subscriptions_create(req: WebhookSubscriptionCreateIn, request: Request):
    """创建 webhook subscription；严格符合 FIELD_REGISTRY WebhookSubscriptionCreated。"""
    target_url = _validate_required_str(req.target_url, "target_url", max_len=MAX_TARGET_URL_LEN)
    if not isinstance(req.event_types, list) or not req.event_types:
        raise HTTPException(status_code=400, detail="invalid event_types")
    event_types_clean: list[str] = []
    for et in req.event_types:
        event_types_clean.append(_validate_required_str(et, "event_types"))
    secret = _validate_optional_str(req.secret, "secret")
    store = request.state.store
    try:
        sub = store.create_webhook_subscription(
            target_url=target_url,
            event_types=event_types_clean,
            secret=secret,
            is_enabled=req.is_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub


@router.get("/v1/webhooks/subscriptions", response_model=WebhookSubscriptionListOut)
def v1_webhooks_subscriptions_list(request: Request):
    """查询 webhook subscriptions；严格符合 FIELD_REGISTRY WebhookSubscriptionListOK。"""
    store = request.state.store
    return {"subscriptions": store.list_webhook_subscriptions()}


@router.get("/v1/webhooks/deliveries", response_model=WebhookDeliveryListOut)
def v1_webhooks_deliveries_list(request: Request):
    """查询 webhook deliveries；严格符合 FIELD_REGISTRY WebhookDeliveriesListOK。"""
    store = request.state.store
    return {"deliveries": store.list_webhook_deliveries()}
