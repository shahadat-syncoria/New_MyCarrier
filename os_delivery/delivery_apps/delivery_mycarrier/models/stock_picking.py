# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .sale_order import mc_accessorial_vals


def _carrier_default(field_name):
    """Return a default method that reads from the MyCarrier delivery carrier linked to this picking."""
    def _default(self):
        carrier = self.env['delivery.carrier'].search(
            [('delivery_type', '=', 'mycarrier')], limit=1
        )
        if not carrier:
            return False
        val = carrier[field_name]
        return val.id if hasattr(val, '_name') else bool(val)
    return _default


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    mycarrier_is_active = fields.Boolean(compute='_compute_mycarrier_is_active')
    mycarrier_create_quote = fields.Boolean(related='carrier_id.mycarrier_create_quote')
    mycarrier_webhook_received = fields.Boolean('MC Webhook Received', copy=False, readonly=True)

    # MyCarrier workflow status (separate from picking state so we don't break compute)
    mycarrier_status = fields.Selection([
        ('pending', 'Pending'),
        ('ordered', 'Order Created'),
        ('rated', 'Rated'),
        ('dispatched', 'Dispatched'),
    ], string='MC Status', default='pending', copy=False, tracking=True)

    # Rates JSON stored after RATE_ONLY so the Select Rate wizard can open without re-calling API
    mycarrier_rates_json = fields.Text('MC Rates JSON', copy=False)

    # ── Origin accessorials ───────────────────────────────────────────────────
    origin_location_type = fields.Many2one(
        'mycarrier.location.type', string='Origin Location Type',
        default=_carrier_default('mycarrier_default_origin_location_type'),
    )
    origin_inside_pickup = fields.Boolean(
        'Inside Pickup',
        default=_carrier_default('mycarrier_default_origin_inside_pickup'),
    )
    origin_liftgate_pickup = fields.Boolean(
        'Liftgate Pickup',
        default=_carrier_default('mycarrier_default_origin_liftgate_pickup'),
    )
    origin_protect_from_freeze = fields.Boolean(
        'Protect From Freeze',
        default=_carrier_default('mycarrier_default_origin_protect_from_freeze'),
    )
    origin_single_shipment = fields.Boolean(
        'Single Shipment',
        default=_carrier_default('mycarrier_default_origin_single_shipment'),
    )
    origin_inbond_freight = fields.Boolean(
        'In Bond Freight',
        default=_carrier_default('mycarrier_default_origin_inbond_freight'),
    )

    # ── Destination accessorials ──────────────────────────────────────────────
    dest_location_type = fields.Many2one(
        'mycarrier.location.type', string='Destination Location Type',
        default=_carrier_default('mycarrier_default_dest_location_type'),
    )
    dest_delivery_appointment = fields.Boolean(
        'Delivery Appointment',
        default=_carrier_default('mycarrier_default_dest_delivery_appointment'),
    )
    dest_inside_delivery = fields.Boolean(
        'Inside Delivery',
        default=_carrier_default('mycarrier_default_dest_inside_delivery'),
    )
    dest_liftgate_delivery = fields.Boolean(
        'Liftgate Delivery',
        default=_carrier_default('mycarrier_default_dest_liftgate_delivery'),
    )
    dest_notify_delivery = fields.Boolean(
        'Notify Before Delivery',
        default=_carrier_default('mycarrier_default_dest_notify_delivery'),
    )
    dest_sort_segregate_delivery = fields.Boolean(
        'Sort/Segregate Delivery',
        default=_carrier_default('mycarrier_default_dest_sort_segregate_delivery'),
    )

    # ── Order references ──────────────────────────────────────────────────────
    mycarrier_po_number = fields.Char('PO Number', copy=False)
    mycarrier_customer_bol_number = fields.Char('Customer BOL Number', copy=False)
    mycarrier_special_instructions = fields.Text('Special Instructions')
    mycarrier_cargo_value = fields.Float(
        'Cargo Value (Insurance)', digits=(16, 2), default=0.0,
        help='Declared cargo value for insurance. Affects quoted rate. Set to 0 for no coverage.',
    )

    # ── Rate selection (populated by get-rates wizard) ────────────────────────
    mycarrier_quote_id = fields.Char('MC Quote ID', copy=False)
    mycarrier_carrier_quote_number = fields.Char('MC Carrier Quote #', copy=False)
    mycarrier_selected_carrier = fields.Char('MC Carrier (SCAC)', copy=False)
    mycarrier_selected_level = fields.Char('MC Service Level', copy=False)
    mycarrier_transit_days = fields.Integer('MC Transit Days', copy=False)
    mycarrier_total_cost = fields.Float('MC Quoted Cost', digits=(16, 2), copy=False)
    mycarrier_charge_items = fields.Char('MC Charge Items (JSON)', copy=False)
    mycarrier_rated_at = fields.Datetime('MC Rated At', copy=False)

    # ── Post-dispatch (populated by send_shipping) ────────────────────────────
    mycarrier_shipment_id = fields.Char('MC Shipment ID', copy=False)
    mycarrier_pro_number = fields.Char('MC PRO Number', copy=False)
    mycarrier_bol_number = fields.Char('MC BOL Number', copy=False)
    mycarrier_pickup_number = fields.Char('MC Pickup Confirmation', copy=False)
    mycarrier_security_key = fields.Char('MC Security Key', copy=False)
    mycarrier_tracking_url = fields.Char('MC Tracking URL', copy=False)
    mycarrier_bol_url = fields.Char('MC BOL URL', copy=False)
    mycarrier_carrier_name = fields.Char('MC Carrier Name', copy=False)
    mycarrier_pickup_date = fields.Char('MC Pickup Date', copy=False)
    mycarrier_estimated_delivery = fields.Char('MC Est. Delivery', copy=False)
    mycarrier_final_cost = fields.Float('MC Final Cost', digits=(16, 2), copy=False)
    mycarrier_tracking_status = fields.Char('MC Tracking Status', copy=False, tracking=True)
    mycarrier_actual_pickup_date = fields.Char('MC Actual Pickup', copy=False)
    mycarrier_status_exception = fields.Boolean('MC Shipment Exception', copy=False, tracking=True)

    @api.depends('carrier_id', 'carrier_id.delivery_type')
    def _compute_mycarrier_is_active(self):
        for rec in self:
            rec.mycarrier_is_active = (
                bool(rec.carrier_id) and rec.carrier_id.delivery_type == 'mycarrier'
            )

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        # Created from an SO: accessorials chosen there, else the delivery method's MyCarrier defaults
        for picking in pickings.filtered(lambda p: p.carrier_id.delivery_type == 'mycarrier' and p.sale_id):
            order = picking.sale_id
            picking.write(
                mc_accessorial_vals(order) if order.mycarrier_accessorials_set
                else mc_accessorial_vals(picking.carrier_id, 'mycarrier_default_')
            )
        return pickings

    def _pre_put_in_pack_hook(self, move_line_ids):
        # MyCarrier: skip stock_delivery's "Package Details" wizard. The package is created directly
        # and its Package Type / Shipping Weight are set on the package via the Packages smart button.
        if len(self) == 1 and self.carrier_id.delivery_type == 'mycarrier':
            return self._check_destinations(move_line_ids)
        return super()._pre_put_in_pack_hook(move_line_ids)

    def mycarrier_action_create_order(self):
        """Button 1: RATE_ONLY — creates the order on MyCarrier, stores quoteId + rates."""
        self.ensure_one()
        if not self.carrier_id or self.carrier_id.delivery_type != 'mycarrier':
            raise UserError(_('Please set a MyCarrier delivery method on this picking.'))
        return self.carrier_id.mycarrier_action_create_order(self)

    def mycarrier_action_update_order(self):
        """Button 1b: Re-submit updated order to MyCarrier, clearing stale rate selection."""
        self.ensure_one()
        if not self.carrier_id or self.carrier_id.delivery_type != 'mycarrier':
            raise UserError(_('Please set a MyCarrier delivery method on this picking.'))
        return self.carrier_id.mycarrier_action_update_order(self)

    def mycarrier_action_update_quote(self):
        """Re-save the MyCarrier quote with this delivery's data (provider option: Create MyCarrier Quote)."""
        self.ensure_one()
        if not self.carrier_id or self.carrier_id.delivery_type != 'mycarrier':
            raise UserError(_('Please set a MyCarrier delivery method on this picking.'))
        return self.carrier_id.mycarrier_action_update_quote(self)

    def mycarrier_action_select_rate(self):
        """Button 2: Fetches rates for the created order and opens selection wizard."""
        self.ensure_one()
        if self.mycarrier_status not in ('ordered', 'rated') and not self.mycarrier_create_quote:
            raise UserError(_('Please create a MyCarrier order first.'))
        if not self.env.context.get('mycarrier_accessorials_done'):
            # Accessorials first; "Show Rates" in that wizard re-enters here with the flag set
            return self.env['mycarrier.so.accessorial']._open_for_picking(self)
        return self.carrier_id.mycarrier_action_select_rate(self)

    def mycarrier_action_dispatch(self):
        """Button 3: Dispatch the pre-rated shipment to MyCarrier."""
        self.ensure_one()
        if self.mycarrier_create_quote and self.mycarrier_status != 'rated':
            # First click: pick the rate (the SO's / this delivery's previous one is preselected)
            return self.with_context(mycarrier_accessorials_done=True).mycarrier_action_select_rate()
        if self.mycarrier_status != 'rated':
            raise UserError(_('Please select a rate before dispatching.'))
        self.send_to_shipper()
