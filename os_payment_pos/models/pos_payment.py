# -*- coding: utf-8 -*-

from odoo import fields, models


class PosPaymentCardName(models.Model):
    _inherit = 'pos.payment'

    card_name = fields.Char('Card Name')
