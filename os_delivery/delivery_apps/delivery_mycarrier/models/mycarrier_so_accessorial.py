# -*- coding: utf-8 -*-
from odoo import _, fields, models

from .sale_order import mc_accessorial_vals

class MycarrierSoAccessorial(models.TransientModel):
    _name = 'mycarrier.so.accessorial'
    _description = 'MyCarrier Accessorials (Sales Order / Delivery)'

    choose_wizard_id = fields.Many2one('choose.delivery.carrier', ondelete='cascade')
    order_id = fields.Many2one('sale.order', ondelete='cascade')
    picking_id = fields.Many2one('stock.picking', ondelete='cascade')
    carrier_id = fields.Many2one('delivery.carrier', required=True, ondelete='cascade')

    origin_location_type = fields.Many2one('mycarrier.location.type', string='Origin Location Type')
    origin_inside_pickup = fields.Boolean('Inside Pickup')
    origin_liftgate_pickup = fields.Boolean('Liftgate Pickup')
    origin_protect_from_freeze = fields.Boolean('Protect From Freeze')
    origin_single_shipment = fields.Boolean('Single Shipment')
    origin_inbond_freight = fields.Boolean('In Bond Freight')
    dest_location_type = fields.Many2one('mycarrier.location.type', string='Destination Location Type')
    dest_delivery_appointment = fields.Boolean('Delivery Appointment')
    dest_inside_delivery = fields.Boolean('Inside Delivery')
    dest_liftgate_delivery = fields.Boolean('Liftgate Delivery')
    dest_notify_delivery = fields.Boolean('Notify Before Delivery')
    dest_sort_segregate_delivery = fields.Boolean('Sort/Segregate Delivery')

    def _prefill_values(self, order, carrier):
        """Existing data: what the SO already holds, else the carrier's defaults."""
        if order.mycarrier_accessorials_set:
            return mc_accessorial_vals(order)
        return mc_accessorial_vals(carrier, 'mycarrier_default_')

    def _open_for_picking(self, picking):
        """Delivery's Select Rate: show the delivery's current accessorials before fetching rates."""
        wizard = self.create(dict(
            mc_accessorial_vals(picking), picking_id=picking.id, carrier_id=picking.carrier_id.id,
        ))
        return {
            'name': _('MyCarrier Accessorials'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': self._name,
            'res_id': wizard.id,
            'target': 'new',
        }

    def _reopen_choose_wizard(self):
        return {
            'name': _('Add a shipping method'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'choose.delivery.carrier',
            'res_id': self.choose_wizard_id.id,
            'target': 'new',
        }

    def action_show_rates(self):
        """Save the accessorials on the SO, then run the normal Get Rate."""
        self.ensure_one()
        if self.picking_id:
            self.picking_id.write(mc_accessorial_vals(self))
            return self.picking_id.with_context(mycarrier_accessorials_done=True).mycarrier_action_select_rate()
        self.order_id.write(dict(mc_accessorial_vals(self), mycarrier_accessorials_set=True))
        self.order_id._mycarrier_push_accessorials()
        return self.choose_wizard_id.with_context(mycarrier_accessorials_done=True).update_price()

    def action_back(self):
        self.ensure_one()
        if self.picking_id:
            return {'type': 'ir.actions.act_window_close'}
        return self._reopen_choose_wizard()
