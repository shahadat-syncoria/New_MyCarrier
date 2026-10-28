# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

import pprint
import re
from odoo.addons.syncoria_shopify.shopify.utils import *
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)
from odoo import exceptions


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    shopify_id = fields.Char(string="Fulfillment ID", copy=False)
    shopify_order_id = fields.Char(string="Shopify Order ID", related='sale_id.shopify_id')
    shopify_status = fields.Char(copy=False, string='Shipment Status')
    shopify_service = fields.Char(copy=False, string='Shopify Service')
    shopify_track_updated = fields.Boolean(default=False, readonly=True, copy=False)
    shopify_tracking_urls = fields.Char(string="Shopify Tracking Url", copy=False)
    shopify_tracking_company = fields.Char(string="Shopify Tracking Company", copy=False)
    shopify_location_id = fields.Char(string='Shopify Location ID')
    shopify_tracking_number = fields.Char(string='Shopify Tracking Number')

    def get_fulfillment_order(self):
        for rec in self:
            marketplace_instance_id = rec.sale_id.marketplace_instance_id
            url = '/orders/%s/fulfillment_orders.json' % rec.sale_id.shopify_id
            headers = {
                'X-Service-Key': marketplace_instance_id.token,
            }
            type_req = 'GET'
            fulfillment_orders, next_link = self.env['marketplace.connector'].shopify_api_call(
                headers=headers,
                url=url,
                type=type_req,
                marketplace_instance_id=marketplace_instance_id,
            )
            if fulfillment_orders.get('errors'):
                raise exceptions.UserError(_(fulfillment_orders.get('errors')))
            else:
                return fulfillment_orders

    def create_shopify_fulfillment(self):
        for rec in self:
            if not rec.location_id.warehouse_id.shopify_location_id and not rec.is_dropship:
                raise exceptions.ValidationError('This location has not been mapped')
            res = rec.get_fulfillment_order()
            fulfillment_orders = res.get('fulfillment_orders')
            shopify_location_id = rec.location_id.warehouse_id.shopify_location_id.shopify_invent_id
            """
                IF LOCATION MATCHES, THAT MEANS WE ARE FULFILLING FROM THE RIGHT LOCATION
                IF NOT, WE HAVE TO MOVE THE LOCATION
            """
            fulfillment_order = False
            fulfillable_orders = [order for order in fulfillment_orders if order['status'] in ('open', 'in_progress', 'scheduled')]
            for fulfillment in fulfillable_orders:

                if fulfillment['assigned_location_id'] == int(shopify_location_id):
                    fulfillment_order = fulfillment
                    break
            if not fulfillment_order:
                fulfillment_order = rec.move_shopify_fulfillment_order(fulfillable_orders, shopify_location_id)
            if fulfillment_order:
                fulfillment_order_id = fulfillment_order.get('id')
                line_items = fulfillment_order.get('line_items')
                line_map_dict = {}
                for line in line_items:
                    line_map_dict[str(line['line_item_id'])] = line['id']
                move_ids = rec.move_ids.filtered(lambda m: m.quantity > 0)
                fulfillment_order_line_items = []
                delivery_products = self.env['delivery.carrier'].search([]).product_id
                for move in move_ids:
                    if move.product_id in delivery_products:
                        continue
                    shopify_line_item_id = move.sale_line_id.shopify_id
                    fulfillment_order_line = {'id': line_map_dict.get(shopify_line_item_id),
                                              'quantity': int(move.quantity)}
                    fulfillment_order_line_items.append(fulfillment_order_line)
                if move_ids:
                    fulfillment_dict = {
                        'message': 'The package was shipped',
                        'notify_customer': True,
                        'tracking_info': {'number': rec.carrier_tracking_ref or rec.shopify_tracking_number or ''},
                        'line_items_by_fulfillment_order': [{'fulfillment_order_id': fulfillment_order_id,
                                                             'fulfillment_order_line_items': fulfillment_order_line_items}]
                    }
                    marketplace_instance_id = rec.sale_id.marketplace_instance_id
                    url = '/fulfillments.json'
                    headers = {
                        'X-Service-Key': marketplace_instance_id.token,
                    }
                    type_req = 'POST'
                    data = {
                        'fulfillment': fulfillment_dict
                    }
                    fulfillment_res, next_link = self.env['marketplace.connector'].shopify_api_call(
                        headers=headers,
                        url=url,
                        type=type_req,
                        marketplace_instance_id=marketplace_instance_id,
                        data=data
                    )
                    if fulfillment_res.get('errors'):
                        rec.message_post(body=fulfillment_res.get('errors'))
                    else:
                        rec.shopify_id = fulfillment_res.get('fulfillment').get('id')
                        rec.marketplace_instance_id = marketplace_instance_id

    def move_shopify_fulfillment_order(self, fulfillable_orders, shopify_location_id):
        self.ensure_one()
        for fulfillable_order in fulfillable_orders:
            marketplace_instance_id = self.sale_id.marketplace_instance_id
            url = '/fulfillment_orders/%s/move.json' % fulfillable_order['id']
            headers = {
                'X-Service-Key': marketplace_instance_id.token,
            }
            type_req = 'POST'
            data = {
                'fulfillment_order': {'new_location_id': int(shopify_location_id)}
            }
            fulfillment_res, next_link = self.env['marketplace.connector'].shopify_api_call(
                headers=headers,
                url=url,
                type=type_req,
                marketplace_instance_id=marketplace_instance_id,
                data=data
            )
            if fulfillment_res.get('errors'):
                self.message_post(body=fulfillment_res.get('errors'))
            else:
                return fulfillment_res.get('moved_fulfillment_order')


# class InheritedStockLocation(models.Model):
#     _inherit = 'stock.location'
#
#     shopify_location_id = fields.Many2one("shopify.warehouse", string="Shopify Warehouse")
#     shopify_invent_id = fields.Char("Shopify Location ID", related="shopify_location_id.shopify_invent_id")
#
#     _sql_constraints = [
#         ('shopify_location_id', 'unique (shopify_location_id)', 'Only 1 odoo map 1 shopify location.'),
#     ]

class InheritedStockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    shopify_location_id = fields.Many2one("shopify.warehouse", string="Shopify Warehouse")
    shopify_invent_id = fields.Char("Shopify Location ID", related="shopify_location_id.shopify_invent_id")

    _sql_constraints = [
        ('shopify_location_id', 'unique (shopify_location_id)', 'Only 1 odoo map 1 shopify location.'),
    ]


class InheritedStockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        res = super(InheritedStockMove, self).write(vals)
        for rec in self:
            if rec.state == 'done' and rec.product_id:
                rec.product_id.shopify_need_sync = True
        return res
