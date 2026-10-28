# -*- coding: utf-8 -*-
from odoo import fields, models


class MycarrierLocationType(models.Model):
    _name = 'mycarrier.location.type'
    _description = 'MyCarrier Location Type'
    _order = 'sequence, name'

    name = fields.Char('Type', required=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Location type already exists.'),
    ]
