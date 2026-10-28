from odoo import models, fields, api, _


class Paymentprovider(models.Model):
    _inherit = 'account.journal'

    account_id = fields.Many2one(
        string='account',
        comodel_name='omni.account',
        ondelete='restrict',
    )
    token = fields.Char(copy=False)
    omnisync_active = fields.Boolean(
        string='Active',
        compute='_compute_omnisync_active')

    def _compute_omnisync_active(self):
        for record in self:
            record.omnisync_active = False


# class AccountMove(models.Model):
#     _inherit = 'account.move'
#
#     @api.depends('reconciled_payment_ids')
#     def _compute_payment_count(self):
#         """This fix only given for version 19.0"""
#         for invoice in self:
#             try:
#                 invoice.payment_count = len(invoice.reconciled_payment_ids)
#             except Exception:
#                 invoice.payment_count = 0
#
#
# class AccountPayment(models.Model):
#     _inherit = 'account.payment'
#
#
#     ref = fields.Char(related='memo',string="Ref")
#
#     def _search_reconciled_invoice_ids(self, operator, value):
#         try:
#             if operator not in ('in', '='):
#                 return NotImplemented
#             move_ids = self.env['account.move'].browse(value).reconciled_payment_ids.ids
#         except Exception:
#             move_ids = []
#         return [('id', 'in', move_ids)]