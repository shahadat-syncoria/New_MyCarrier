# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

from odoo import models, fields, api, _

class Paymentprovider(models.Model):
    _inherit = 'payment.provider'

    
    account_id = fields.Many2one(
        string='account',
        comodel_name='omni.account',
        ondelete='restrict',
    )
    # test_transaction_schedule_id = fields.Char(string="Test Transaction Schedule ID")
    token = fields.Char(copy=False)
    omnisync_active = fields.Boolean(
        string='Active',
        compute='_compute_omnisync_active')

    def _compute_omnisync_active(self):
        for record in self:
            record.omnisync_active = False

    @api.model_create_multi
    def create(self, vals_list):
        providers = super().create(vals_list)
        providers._sync_checkout_tokenization_fields()
        return providers

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('skip_checkout_tokenization_sync'):
            self._sync_checkout_tokenization_fields()
        return result

    def _sync_checkout_tokenization_fields(self):
        for provider in self:
            vals = {}
            if provider.code == 'bamborachk' and not provider.allow_tokenization:
                vals['allow_tokenization'] = True
            elif provider.code == 'monerischeckout' and 'moneris_token' in provider._fields:
                if provider.moneris_token and not provider.allow_tokenization:
                    vals['allow_tokenization'] = True
                elif not provider.moneris_token and provider.allow_tokenization:
                    vals['allow_tokenization'] = False
            if vals:
                provider.with_context(skip_checkout_tokenization_sync=True).write(vals)


# class AccountPayment(models.Model):
#     _inherit = 'account.payment'
#
#     is_clik2pay_sync_button_visible = fields.Boolean(compute='_check_is_clik2pay_sync_visible')
#     resolvepay_payment_date = fields.Char(string="Resolve Pay payment datetime")
#     rp_payout_transaction_id = fields.Char(string="Resolve Pay Payout Transaction Id")
#     rp_payout_id = fields.Char(string="Resolve Pay Payout Id")
#     rp_payout_transaction_type = fields.Selection(
#         selection=[
#             ('advance', 'advance'),
#             ('payment', 'payment'),
#             ('refund', 'refund'),
#             ('monthly_fee', 'monthly_fee'),
#             ('annual_fee', 'annual_fee'),
#             ('non_advanced_invoice_fee', 'non_advanced_invoice_fee'),
#             ('merchant_payment', 'merchant_payment'),
#             ('mdr_extension', 'mdr_extension'),
#             ('credit_note', 'credit_note'),
#         ],
#         string='Resolve Pay Transaction Type',
#     )
#     rp_payout_transaction_amount_gross = fields.Float('amount_gross')
#     rp_payout_transaction_amount_fee = fields.Float('amount_fee')
#     rp_payout_transaction_amount_net = fields.Float('amount_net')
#
#
#     def update_payment_refund_status(self):
#         for rec in self:
#             pass
