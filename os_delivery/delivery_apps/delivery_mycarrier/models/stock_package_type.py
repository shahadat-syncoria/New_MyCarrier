# -*- coding: utf-8 -*-
from odoo import models

from .delivery_carrier import _MC_SHIPPING_UNIT_TYPES, _mc_unit_type_name


class StockPackageType(models.Model):
    _inherit = 'stock.package.type'

    def _compute_length_uom_name(self):
        super()._compute_length_uom_name()
        # MyCarrier unit types are entered in inches (the value sent to the API); Odoo's label is mm or ft only.
        for package_type in self.filtered(lambda t: _mc_unit_type_name(t.name) in _MC_SHIPPING_UNIT_TYPES):
            package_type.length_uom_name = 'in'
