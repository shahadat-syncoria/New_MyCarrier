# -*- coding: utf-8 -*-
from odoo import _, fields, models


class MycarrierSoRate(models.TransientModel):
    _name = 'mycarrier.so.rate'
    _description = 'MyCarrier SO Rate Option'
    _order = 'id'  # created contract-first, then cheapest

    wizard_id = fields.Many2one('choose.delivery.carrier', ondelete='cascade')
    order_id = fields.Many2one('sale.order', ondelete='cascade')
    carrier_id = fields.Many2one('delivery.carrier')
    is_selected = fields.Boolean('Selected')

    carrier_scac = fields.Char('Carrier')
    service_level = fields.Char()
    service_level_label = fields.Char('Service')
    pricing_type = fields.Char('Type')
    total_cost = fields.Float('Price (USD)', digits=(16, 2))
    currency_code = fields.Char('Currency')
    transit_days = fields.Integer('Transit (days)')
    quote_expiry = fields.Char('Expiry')
    carrier_quote_number = fields.Char('Quote #')
    has_unknown_charge = fields.Boolean()
    estimated_delivery = fields.Char('Est. Delivery')

    def action_select_this_rate(self):
        self.ensure_one()
        # Deselect all, select this one
        self.wizard_id.mycarrier_rate_ids.write({'is_selected': False})
        self.is_selected = True
        self.wizard_id.write({
            'delivery_price': self.total_cost,
            'display_price': self.total_cost,
        })
        return {
            'name': _('Add a shipping method'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'choose.delivery.carrier',
            'res_id': self.wizard_id.id,
            'target': 'new',
        }
