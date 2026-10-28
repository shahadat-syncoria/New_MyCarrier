# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockQuantPackage(models.Model):
    _inherit = 'stock.quant.package'

    mycarrier_hazmat = fields.Boolean('HazMat')
    mycarrier_stackable = fields.Boolean('Stackable')
    mycarrier_commodity_class = fields.Char('Freight Class')
    mycarrier_commodity_nmfc = fields.Char('NMFC Code')
    mycarrier_commodity_sub = fields.Char('Sub')
    mycarrier_package_count = fields.Integer(
        'Piece Count', default=1,
        help='Number of pieces sent as the commodity quantity for this package (package-wise mode).',
    )
    mycarrier_quote_build_mode = fields.Char(compute='_compute_mycarrier_quote_build_mode')

    @api.depends_context('company')
    def _compute_mycarrier_quote_build_mode(self):
        carrier = self.env['delivery.carrier'].search([('delivery_type', '=', 'mycarrier')], limit=1)
        for package in self:
            package.mycarrier_quote_build_mode = carrier.mycarrier_quote_build_mode or 'product'
