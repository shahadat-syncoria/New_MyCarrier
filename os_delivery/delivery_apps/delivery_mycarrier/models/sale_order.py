# -*- coding: utf-8 -*-
from odoo import api, fields, models


# Accessorial fields shared by sale.order, stock.picking and the SO accessorial wizard.
# The carrier's defaults live in mycarrier_default_<field>.
MC_ACCESSORIAL_FIELDS = [
    'origin_location_type', 'origin_inside_pickup', 'origin_liftgate_pickup', 'origin_protect_from_freeze',
    'origin_single_shipment', 'origin_inbond_freight',
    'dest_location_type', 'dest_delivery_appointment', 'dest_inside_delivery', 'dest_liftgate_delivery',
    'dest_notify_delivery', 'dest_sort_segregate_delivery',
]


def mc_accessorial_vals(record, prefix=''):
    """Write values of the accessorial fields read from `record` (field names optionally prefixed)."""
    return {
        f: (record[prefix + f].id if record._fields[prefix + f].type == 'many2one' else record[prefix + f])
        for f in MC_ACCESSORIAL_FIELDS
    }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mycarrier_is_active = fields.Boolean(compute='_compute_mycarrier_is_active')

    # Rate chosen in the Add Shipping wizard: preselected next time, and by the delivery's Select Rate
    mycarrier_quote_id = fields.Char('MC Quote ID', copy=False)
    mycarrier_selected_carrier = fields.Char('MC Carrier', copy=False)
    mycarrier_selected_level = fields.Char('MC Service Level', copy=False)
    mycarrier_selected_price = fields.Float('MC Selected Price', digits=(16, 2), copy=False)
    mycarrier_carrier_quote_number = fields.Char('MC Carrier Quote Number', copy=False)

    # MyCarrier accessorials chosen in the Get Rate step (same names as on stock.picking)
    mycarrier_accessorials_set = fields.Boolean(copy=False)
    origin_location_type = fields.Many2one('mycarrier.location.type', string='Origin Location Type', copy=False)
    origin_inside_pickup = fields.Boolean('Inside Pickup', copy=False)
    origin_liftgate_pickup = fields.Boolean('Liftgate Pickup', copy=False)
    origin_protect_from_freeze = fields.Boolean('Protect From Freeze', copy=False)
    origin_single_shipment = fields.Boolean('Single Shipment', copy=False)
    origin_inbond_freight = fields.Boolean('In Bond Freight', copy=False)
    dest_location_type = fields.Many2one('mycarrier.location.type', string='Destination Location Type', copy=False)
    dest_delivery_appointment = fields.Boolean('Delivery Appointment', copy=False)
    dest_inside_delivery = fields.Boolean('Inside Delivery', copy=False)
    dest_liftgate_delivery = fields.Boolean('Liftgate Delivery', copy=False)
    dest_notify_delivery = fields.Boolean('Notify Before Delivery', copy=False)
    dest_sort_segregate_delivery = fields.Boolean('Sort/Segregate Delivery', copy=False)

    @api.depends('carrier_id.delivery_type')
    def _compute_mycarrier_is_active(self):
        for order in self:
            order.mycarrier_is_active = order.carrier_id.delivery_type == 'mycarrier'

    def _mycarrier_push_accessorials(self):
        """Accessorials -> the open MyCarrier deliveries of the order (until dispatched).

        The SO's own choices once the Get Rate wizard was used, else the delivery method's MyCarrier defaults.
        """
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda p: p.carrier_id.delivery_type == 'mycarrier'
                and p.state not in ('done', 'cancel') and p.mycarrier_status != 'dispatched'
            )
            if order.mycarrier_accessorials_set:
                pickings.write(mc_accessorial_vals(order))
            else:
                for picking in pickings:
                    picking.write(mc_accessorial_vals(picking.carrier_id, 'mycarrier_default_'))

    def _mycarrier_push_quote(self):
        """Quote saved on the SO -> its open MyCarrier deliveries (they still have to confirm it at dispatch)."""
        for order in self.filtered(lambda o: o.carrier_id.mycarrier_create_quote and o.mycarrier_quote_id):
            order.picking_ids.filtered(
                lambda p: p.carrier_id.delivery_type == 'mycarrier'
                and p.state not in ('done', 'cancel') and p.mycarrier_status != 'dispatched'
            ).write({
                'mycarrier_quote_id': order.mycarrier_quote_id,
                'mycarrier_carrier_quote_number': order.mycarrier_carrier_quote_number,
                'mycarrier_selected_carrier': order.mycarrier_selected_carrier,
                'mycarrier_selected_level': order.mycarrier_selected_level,
                'mycarrier_total_cost': order.mycarrier_selected_price,
            })

    def _action_confirm(self):
        res = super()._action_confirm()
        # Deliveries only link to the SO after they are created, so copy accessorials and quote once confirmed
        mycarrier_orders = self.filtered('mycarrier_is_active')
        mycarrier_orders._mycarrier_push_accessorials()
        mycarrier_orders._mycarrier_push_quote()
        return res
