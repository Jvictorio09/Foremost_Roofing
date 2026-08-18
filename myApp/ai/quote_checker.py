"""Audits an order for missing materials, unusual discounts, and inventory gaps."""
import json
from decimal import Decimal

from .providers import AIProviderError, get_provider


SYSTEM_PROMPT = """You are an experienced roofing operations auditor for a construction
materials supplier. Given an order summary, you flag concerns a coordinator should
review before sending the job to production. Focus on:

1. Missing materials that a roof of this type typically requires
   (e.g. gutters, downspouts, flashing, ridge caps, fasteners).
2. Discount levels that are unusually high for the order amount.
3. Inventory shortfalls relative to the order requirements.
4. Anything else a seasoned operator would notice.

Respond ONLY with a JSON object of this shape:
{
  "severity": "low" | "medium" | "high",
  "findings": [
    {"category": "missing_material" | "discount" | "inventory" | "other",
     "message": "<short, specific, actionable>"}
  ],
  "summary": "<one-sentence overall verdict>"
}

If nothing is wrong, return findings: [] and severity: "low".
"""


def _build_user_prompt(order, inventory_snapshot):
    items = []
    if hasattr(order, 'quotation'):
        for it in order.quotation.items.all():
            items.append({
                'description': it.description,
                'quantity': float(it.quantity),
                'unit': it.unit,
                'unit_price': float(it.unit_price),
            })
    payload = {
        'order_number': order.number,
        'customer': order.customer.name,
        'roof_type': order.roof_type,
        'description': order.description,
        'amount': float(order.amount),
        'discount': float(order.discount),
        'discount_pct': float(order.discount / order.amount * 100) if order.amount else 0,
        'quotation_items': items,
        'inventory_snapshot': inventory_snapshot,
    }
    return json.dumps(payload, indent=2, default=str)


def check_order(order_id: int, provider_name: str | None = None) -> dict:
    """Run an AI quote check for a single order. Saved as an AICheck row.

    Returns the AICheck.id so async_task callers can look it up.
    """
    from myApp.models import AICheck, InventoryItem, Order

    order = Order.objects.select_related('customer').get(pk=order_id)
    inventory_snapshot = [
        {'sku': i.sku, 'name': i.name, 'on_hand': float(i.on_hand), 'unit': i.unit}
        for i in InventoryItem.objects.all()[:50]
    ]

    check = AICheck.objects.create(
        order=order,
        kind=AICheck.Kind.QUOTE_CHECK,
        status=AICheck.Status.RUNNING,
    )
    try:
        provider = get_provider(provider_name)
        response = provider.complete(
            system=SYSTEM_PROMPT,
            user=_build_user_prompt(order, inventory_snapshot),
            max_tokens=1024,
        )
        data = response.as_json()
        check.provider = response.provider
        check.model = response.model
        check.severity = data.get('severity') or 'low'
        check.summary = data.get('summary') or ''
        check.findings = data.get('findings') or []
        check.raw_text = response.text
        check.status = AICheck.Status.DONE
        check.save()
    except AIProviderError as e:
        check.status = AICheck.Status.FAILED
        check.summary = str(e)
        check.save()
    except Exception as e:
        check.status = AICheck.Status.FAILED
        check.summary = f'AI call failed: {e}'
        check.save()
    return check.id
