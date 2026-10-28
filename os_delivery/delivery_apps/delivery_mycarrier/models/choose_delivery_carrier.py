# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class ChooseDeliveryCarrierMyCarrier(models.TransientModel):
    _inherit = 'choose.delivery.carrier'

    mycarrier_is_active = fields.Boolean(compute='_compute_mycarrier_is_active')
    mycarrier_create_quote = fields.Boolean(related='carrier_id.mycarrier_create_quote')
    mycarrier_rate_ids = fields.One2many(
        'mycarrier.so.rate', 'wizard_id', string='Available Rates',
    )

    @api.depends('carrier_id')
    def _compute_mycarrier_is_active(self):
        for rec in self:
            rec.mycarrier_is_active = (
                bool(rec.carrier_id) and rec.carrier_id.delivery_type == 'mycarrier'
            )

    def update_price(self):
        # MyCarrier: ask for the accessorials first; "Show Rates" in that wizard re-enters here with the flag set
        if self.carrier_id.delivery_type == 'mycarrier' and not self.env.context.get('mycarrier_accessorials_done'):
            Accessorial = self.env['mycarrier.so.accessorial']
            wizard = Accessorial.create(dict(
                Accessorial._prefill_values(self.order_id, self.carrier_id),
                choose_wizard_id=self.id, order_id=self.order_id.id, carrier_id=self.carrier_id.id,
            ))
            return {
                'name': _('MyCarrier Accessorials'),
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'res_model': 'mycarrier.so.accessorial',
                'res_id': wizard.id,
                'target': 'new',
            }
        return super().update_price()

    def _get_delivery_rate(self):
        result = super()._get_delivery_rate()
        if self.carrier_id.delivery_type == 'mycarrier' and self.order_id:
            # Fetch rates stored by mycarrier_rate_shipment() and link to this wizard
            rates = self.env['mycarrier.so.rate'].search([
                ('order_id', '=', self.order_id.id),
                ('carrier_id', '=', self.carrier_id.id),
                ('wizard_id', '=', False),
            ])
            # Link through the One2many (not the inverse Many2one) so this also works inside an onchange
            self.mycarrier_rate_ids = [Command.set(rates.ids)]
            # Default: the rate chosen last time on this order if still offered, else the cheapest contract rate
            order = self.order_id
            default = rates.filtered(
                lambda r: order.mycarrier_selected_carrier
                and r.carrier_scac == order.mycarrier_selected_carrier
                and r.service_level == order.mycarrier_selected_level
            )[:1] or rates[:1]
            if default:
                default.is_selected = True
                self.delivery_price = default.total_cost
                self.display_price = default.total_cost
        return result

    def button_confirm(self):
        selected = self.mycarrier_rate_ids.filtered('is_selected')[:1]
        if self.carrier_id.delivery_type == 'mycarrier' and selected:
            self.order_id.write({
                'mycarrier_selected_carrier': selected.carrier_scac,
                'mycarrier_selected_level': selected.service_level,
                'mycarrier_selected_price': selected.total_cost,
                'mycarrier_carrier_quote_number': selected.carrier_quote_number,
            })
        return super().button_confirm()

    def action_create_quote(self):
        """Save the selected rate as a quote at MyCarrier, add the shipping line and keep the quote number."""
        self.ensure_one()
        selected = self.mycarrier_rate_ids.filtered('is_selected')[:1]
        if not selected:
            raise UserError(_('Please select a rate first.'))
        quote = self.carrier_id.mycarrier_create_so_quote(self.order_id, selected.carrier_scac, selected.service_level)
        self.delivery_price = self.display_price = quote['price']
        self.button_confirm()
        self.order_id.write({
            'mycarrier_quote_id': quote['quote_id'],
            'mycarrier_carrier_quote_number': quote['carrier_quote_number'],
            'mycarrier_selected_price': quote['price'],
        })
        self.order_id.message_post(body=_(
            'MyCarrier quote created: quote %(q)s (carrier quote %(cq)s), %(c)s %(l)s, %(p).2f'
        ) % {'q': quote['quote_id'], 'cq': quote['carrier_quote_number'], 'c': selected.carrier_scac,
             'l': selected.service_level, 'p': quote['price']})
        return {'type': 'ir.actions.act_window_close'}
