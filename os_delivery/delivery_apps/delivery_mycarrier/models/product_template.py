# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mycarrier_commodity_class = fields.Char(
        'Freight Class',
        help='NMFC freight class (50 / 55 / 60 / 65 / 70 / 77.5 / 85 / 92.5 / 100 / … / 500).',
    )
    mycarrier_commodity_nmfc = fields.Char('NMFC Code', help='Up to 6 digits.')
    mycarrier_commodity_sub = fields.Char('NMFC Sub-code', help='Up to 10 characters.')
    mycarrier_length = fields.Integer(
        'Length (in)', default=48,
        help='Pallet/package length in inches for LTL freight class computation.',
    )
    mycarrier_width = fields.Integer('Width (in)', default=40)
    mycarrier_height = fields.Integer('Height (in)', default=48)
