# -*- coding: utf-8 -*-
import json

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MycarrierChooseRate(models.TransientModel):
    _name = 'mycarrier.choose.rate'
    _description = 'Select MyCarrier Rate'

    picking_id = fields.Many2one('stock.picking', required=True)
    carrier_id = fields.Many2one('delivery.carrier', required=True)
    quote_id = fields.Char('Quote ID')
    rate_line_ids = fields.One2many('mycarrier.rate.line', 'wizard_id', string='Available Rates')
    breakdown_line_id = fields.Many2one('mycarrier.rate.line')
    breakdown_html = fields.Html(compute='_compute_breakdown_html', sanitize=False)
    rate_warning = fields.Char(compute='_compute_rate_warning')

    @api.depends('rate_line_ids.is_selected')
    def _compute_rate_warning(self):
        for rec in self:
            line = rec.rate_line_ids.filtered('is_selected')[:1]
            rec.rate_warning = line and rec.carrier_id._mc_rate_change_message(
                rec.picking_id, line.carrier_scac, line.service_level, line.total_cost) or False

    @api.depends('breakdown_line_id')
    def _compute_breakdown_html(self):
        for rec in self:
            line = rec.breakdown_line_id
            if not line:
                rec.breakdown_html = False
                continue
            items = json.loads(line.charge_items_json or '[]')
            rows = Markup('').join(
                Markup('<tr><td>{}</td><td>{}</td><td class="text-end">{:.2f}</td></tr>').format(
                    escape(i.get('code', '')),
                    escape(i.get('description') or i.get('name') or i.get('chargeDescription') or ''),
                    float(i.get('amount', 0.0)),
                )
                for i in items
            )
            rec.breakdown_html = Markup(
                '<strong>{} — {}</strong>'
                '<table class="table table-sm table-bordered mt-2 mb-1">'
                '<thead><tr><th>Code</th><th>Description</th>'
                '<th class="text-end">Amount (USD)</th></tr></thead>'
                '<tbody>{}</tbody>'
                '<tfoot><tr><th colspan="2">Total</th>'
                '<th class="text-end">{:.2f}</th></tr></tfoot>'
                '</table>'
            ).format(
                escape(line.carrier_scac or ''),
                escape(line.service_level_label or ''),
                rows,
                line.total_cost,
            )

    def action_close_breakdown(self):
        self.ensure_one()
        self.write({'breakdown_line_id': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mycarrier.choose.rate',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Select MyCarrier Rate'),
        }

    def action_confirm(self):
        selected = self.rate_line_ids.filtered('is_selected')
        if not selected:
            raise UserError(_('Please select a rate before confirming.'))
        if len(selected) > 1:
            raise UserError(_('Please select only one rate.'))
        selected = selected[0]

        self.picking_id.write({
            'mycarrier_quote_id': self.quote_id,
            'mycarrier_carrier_quote_number': selected.carrier_quote_number,
            'mycarrier_selected_carrier': selected.carrier_scac,
            'mycarrier_selected_level': selected.service_level,
            'mycarrier_transit_days': selected.transit_days or 0,
            'mycarrier_total_cost': selected.total_cost,
            'mycarrier_charge_items': selected.charge_items_json or '[]',
            'mycarrier_rated_at': fields.Datetime.now(),
            'mycarrier_status': 'rated',
            'carrier_id': self.carrier_id.id,
        })
        # Post order to MC with selected carrier (readyToDispatch: NO)
        self.carrier_id.mycarrier_action_post_rated_order(self.picking_id)
        return {'type': 'ir.actions.act_window_close'}


class MycarrierRateLine(models.TransientModel):
    _name = 'mycarrier.rate.line'
    _description = 'MyCarrier Rate Option'
    _order = 'id'  # created contract-first, then cheapest

    wizard_id = fields.Many2one('mycarrier.choose.rate', ondelete='cascade')
    is_selected = fields.Boolean('Select')

    carrier_scac = fields.Char('Carrier', readonly=True)
    service_level = fields.Char('Level Code', readonly=True)
    service_level_label = fields.Char('Service', readonly=True)
    pricing_type = fields.Char('Pricing', readonly=True)
    total_cost = fields.Float('Price (USD)', digits=(16, 2), readonly=True)
    currency_code = fields.Char('Currency', readonly=True)
    transit_days = fields.Integer('Transit (days)', readonly=True)
    quote_expiry = fields.Char('Quote Expiry', readonly=True)
    carrier_quote_number = fields.Char('Carrier Quote #', readonly=True)
    charge_items_json = fields.Char(readonly=True)
    has_unknown_charge = fields.Boolean('Has Unknown Charge', readonly=True)
    estimated_delivery = fields.Char('Est. Delivery', readonly=True)

    def action_select_this_rate(self):
        self.ensure_one()
        self.wizard_id.rate_line_ids.write({'is_selected': False})
        self.is_selected = True
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mycarrier.choose.rate',
            'res_id': self.wizard_id.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Select MyCarrier Rate'),
        }

    def action_show_breakdown(self):
        self.ensure_one()
        self.wizard_id.write({'breakdown_line_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mycarrier.choose.rate',
            'res_id': self.wizard_id.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Select MyCarrier Rate'),
        }
