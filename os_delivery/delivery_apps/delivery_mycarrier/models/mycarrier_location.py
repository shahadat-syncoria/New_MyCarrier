# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MycarrierLocation(models.Model):
    _name = 'mycarrier.location'
    _description = 'MyCarrier Shipping Location'
    _order = 'name'

    carrier_id = fields.Many2one('delivery.carrier', ondelete='cascade', required=True)
    name = fields.Char('Location Name', required=True)
    address_id = fields.Char('Address ID', help='Use this value as the Origin Address ID on the carrier.')
    location_id = fields.Char('Location ID')
    address_line1 = fields.Char('Address')
    city = fields.Char()
    state = fields.Char('State/Province')
    postal_code = fields.Char('Postal Code')
    country = fields.Char()
    integrated_carriers = fields.Char('Available Carriers', help='JSON list of integrated carrier SCACs.')

    @api.model
    def create_or_update(self, loc_data, carrier_id):
        address_id = str(loc_data.get('addressId') or '').strip()
        existing = self.search([
            ('address_id', '=', address_id),
            ('carrier_id', '=', carrier_id),
        ], limit=1)
        vals = {
            'carrier_id': carrier_id,
            'name': str(loc_data.get('locationId') or loc_data.get('companyName') or address_id),
            'address_id': address_id,
            'location_id': str(loc_data.get('locationId') or ''),
            'address_line1': loc_data.get('streetLine1') or '',
            'city': loc_data.get('city') or '',
            'state': loc_data.get('stateCode') or '',
            'postal_code': loc_data.get('postalCode') or '',
            'country': loc_data.get('country') or '',
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)
