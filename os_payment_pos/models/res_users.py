# -*- coding: utf-8 -*-

from odoo import  fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    has_moneris_rescue_access = fields.Boolean(
        'POS Moneris Rescue',
        implied_group='os_payment_pos.group_pos_moneris_rescue',
    )

