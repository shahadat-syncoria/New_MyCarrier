# delivery_mycarrier — Odoo 18 — Session Context

**Module path:** `odoosync/os_delivery/delivery_apps/delivery_mycarrier/`
**Restart command:** restart Odoo with `-u os_delivery`
**QA API base:** `https://preprod-api.mycarrier.dev`
**PROD API base:** `https://api.mycarriertms.com`
**Auth:** `HTTPBasicAuth(username, api_key)` + `X-Mc-Api-Key: <api_key>` header
**Ponytail mode:** active (lazy/minimal code — no abstractions beyond what's needed)

---

## 3-Button Picking Flow

| Button | Odoo method | API call |
|--------|-------------|----------|
| Create Order | `mycarrier_action_create_order` | `POST /api/v1/orders` — `readyToDispatch: NO`, no carrier |
| Select Rate | `mycarrier_action_select_rate` → wizard → `action_confirm` → `mycarrier_action_post_rated_order` | `POST /api/v1/quote/rate` (RATE_AND_SAVE) then `POST /api/v1/orders` with carrier + `readyToDispatch: NO` |
| Dispatch (Validate) | `mycarrier_send_shipping` | `POST /api/v1/orders` with carrier + `readyToDispatch: YES`, `mode: MANUAL_DISPATCH` |

**`mycarrier_status`** field values: `pending → ordered → rated → dispatched` (`tracking=True` auto-posts chatter on change)

---

## Key Files

### `models/delivery_carrier.py`

#### Constants
```python
_MC_BASE_URLS = {'qa': 'https://preprod-api.mycarrier.dev', 'prod': 'https://api.mycarriertms.com'}
_MC_PAYMENT_DIR = {'PREPAID': 'Prepaid', 'COLLECT': 'Collect', 'THIRD_PARTY': 'ThirdParty'}
_MC_CARRIER_SERVICE = {
    'STD': 'Standard',
    'GUR': 'Afternoon Guaranteed',
    'GUR_NOON': 'Morning Guaranteed',
    'GUR_AM': 'Morning Guaranteed',
}
```

#### Important methods
- `_mc_call(method, path, payload)` — HTTP wrapper, Basic auth + X-Mc-Api-Key
- `_mc_validate_phones(picking)` — raises UserError if origin or dest partner has no phone number
- `_mc_origin_stop(pickup_dt, picking)` — uses `addressId` only (never literal address on origin)
- `_mc_destination_stop(partner, pickup_dt, picking)` — full address + contact + appointmentDetails
- `_mc_rate_payload(action, units, origin, destination, order_ref, picking)` — builds rate payload:
  - `action='RATE_AND_SAVE'` for picking flow
  - `action='RATE_ONLY'` for SO flow
  - `identifiers.orderId = [order_ref]` only when RATE_AND_SAVE
- `_mc_build_dispatch_order_payload(picking, units, carrier_service)` — builds `/api/v1/orders` payload with carrier fields; caller sets `readyToDispatch`
- `_mc_filter_rates(rates)` — keeps rates where `status != 'Error'` AND `totalCost > 0` AND `level != 'GUR_AM'`
- `mycarrier_action_create_order(picking)` — `POST /api/v1/orders`, `readyToDispatch: NO`, empty carrier
- `mycarrier_action_post_rated_order(picking)` — validates phones, `POST /api/v1/orders` with selected carrier + `readyToDispatch: NO`
- `mycarrier_action_update_order(picking)` — calls `mycarrier_action_create_order`, clears local rate fields
- `mycarrier_action_select_rate(picking)` — RATE_AND_SAVE call, then shows rate wizard; quoteId extracted from `data.data.quoteId` → `data.quoteId` → `rate.identifiers.quoteId` → `rate.quoteId` → `picking.name`
- `mycarrier_send_shipping(pickings)` — `POST /api/v1/orders` with carrier + `readyToDispatch: YES`; tracking_number = PRO or mc_order_id

### `models/stock_picking.py` — extra fields on `stock.picking`

```python
mycarrier_status               # Selection: pending/ordered/rated/dispatched (tracking=True)
mycarrier_quote_id             # Char — quoteId from RATE_AND_SAVE response
mycarrier_carrier_quote_number # Char
mycarrier_selected_carrier     # Char — SCAC e.g. "EXLA"
mycarrier_selected_level       # Char — e.g. "STD"
mycarrier_transit_days         # Integer — added this session, needs -u os_delivery
mycarrier_total_cost           # Float
mycarrier_charge_items         # Char — JSON string of charge items
mycarrier_rated_at             # Datetime
mycarrier_shipment_id          # Char
mycarrier_pro_number           # Char
mycarrier_bol_number           # Char
mycarrier_pickup_number        # Char
mycarrier_po_number            # Char
mycarrier_customer_bol_number  # Char
mycarrier_special_instructions # Char
mycarrier_cargo_value          # Float
mycarrier_origin_location_id   # Many2one → mycarrier.location
origin_location_type           # Many2one → mycarrier.location.type
dest_location_type             # Many2one → mycarrier.location.type
# accessorial booleans: origin_liftgate_pickup, origin_inside_pickup,
# origin_protect_from_freeze, origin_single_shipment, origin_inbond_freight,
# dest_liftgate_delivery, dest_delivery_appointment, dest_notify_delivery,
# dest_inside_delivery, dest_sort_segregate_delivery
```

### `wizard/mycarrier_choose_rate.py`

**`MycarrierChooseRate`** (TransientModel):
- Fields: `picking_id`, `carrier_id`, `quote_id`, `rate_line_ids`, `breakdown_line_id`, `breakdown_html`
- `action_confirm` — saves rate fields to picking (including `mycarrier_transit_days`) → calls `carrier_id.mycarrier_action_post_rated_order(picking_id)`
- `action_show_breakdown` / `action_close_breakdown` — inline breakdown toggle (no popup; `target: new` from within dialog replaces dialog in Odoo 18)

**`MycarrierRateLine`** (TransientModel):
- Fields: `carrier_scac`, `service_level`, `service_level_label`, `pricing_type`, `total_cost`, `transit_days`, `carrier_quote_number`, `charge_items_json`, `has_unknown_charge`, `estimated_delivery`, `quote_expiry`, `is_selected`

### `wizard/mycarrier_choose_rate_view.xml`
- Single form view with inline breakdown toggle
- `breakdown_line_id` hidden field drives visibility
- Rate list hidden when `breakdown_line_id` is set
- Select / ✓ Selected buttons per row (no boolean_toggle)
- `decoration-success="is_selected"`, `decoration-warning="has_unknown_charge and not is_selected"`
- Breakdown div with `breakdown_html` field and "← Back to Rates" button
- Confirm button hidden during breakdown

### `security/ir.model.access.csv`
Access rows for: `mycarrier.choose.rate`, `mycarrier.rate.line`, `mycarrier.so.rate`, `mycarrier.location`, `mycarrier.location.type`

---

## Confirmed API Response Structure

### Rate response (`POST /api/v1/quote/rate`)
```json
{
  "data": {
    "quoteId": 39552539,
    "rates": [
      {
        "service": {"carrier": "EXLA", "level": "STD", "pricing": "Contract"},
        "identifiers": {"carrierQuoteNumber": "L5ZBJ24"},
        "priceDetails": {"totalCost": 328.34, "chargeItems": [...]},
        "appointmentDetails": {"transitDays": 2, "delivery": {"estimatedDeliveryDate": "2026/10/07"}},
        "statusInfo": {"status": "Info", "message": "LTL Standard Transit"}
      }
    ],
    "savedQuoteId": null
  },
  "statusCode": 200
}
```
- `quoteId` is at `data.data.quoteId`
- Each rate has `identifiers.carrierQuoteNumber` — NO per-rate quoteId
- `savedQuoteId: null` = quote was not saved against an existing MC order

---

## Known Issues / Pending Work

1. **PRO number / BOL** not returned from `POST /api/v1/orders` immediately — arrives later via MC webhook. No webhook handler currently wired. `bol_url` and `tracking_url` are empty strings after dispatch.

2. **Phone number validation** — `_mc_validate_phones` raises UserError if origin/dest partner is missing phone. **Fishbowl warehouse** contact and **Lumber Inc** contact need phone numbers set in Odoo.

3. **Dispatch creates a new MC order each time** — `POST /api/v1/orders` always creates a new order. If "Create Order" was already clicked, dispatching creates a second MC order. Consider whether "Create Order" button is still needed or should be hidden from the picking form.

4. **`mycarrier_transit_days` field** added this session — needs `-u os_delivery` restart to create DB column.

5. **`mc_api_curls.txt`** — curl reference file for all 6 API calls is at module root.

---

## API Gotchas (verified on QA tenant)

- **Origin stop**: send `addressId` only — never literal address fields (SAIA gives hard error; Estes silently fuzzy-matches)
- **Destination stop**: must have full address + contact (name, addressLine1, city, state, zip, country) + `appointmentDetails.delivery.deliveryDate` — missing any field → `400 "Rates retrieval failed."`
- **Phone**: required on both stops for dispatch — empty phone causes MC portal to block auto-dispatch
- **Rate filtering**: `statusInfo.status == "Info"` = usable (not `"Success"`); filter `status != "Error"` AND `totalCost > 0` AND `level != "GUR_AM"`
- **UNKCHRG**: balancing plug charge (can be large negative) — when present, show `totalCost` only, not the breakdown table
- **Postal code**: max 6 chars, strip spaces (Canadian `A1A 1A1` → `A1A1A1`)
- **Types**: weights/dimensions must be **integers**; freight class is a **string** (`"77.5"`); country = 3-letter (`USA`, `CAN`, `MEX`)
- **GUR_AM**: not active on this tenant — exclude from selectable levels
- **appointmentDetails**: required on BOTH stops; deliveryDate = pickupDate + 5 days buffer
- **Brokerage rates** (EFWW): sort contract before brokerage, then by price — never expose brokerage as default
