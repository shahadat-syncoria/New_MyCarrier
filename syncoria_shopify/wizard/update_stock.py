# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################
import json
import logging
import datetime
from odoo import fields, models, exceptions, _
from odoo.http import request
import re
import pprint
import time

from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class UpdateStockWizard(models.TransientModel):
    _inherit = 'update.stock.wizard'

    def shopify_update_stock_item(self, kwargs):
        Connector = self.env['marketplace.connector']
        active_ids = self._context.get('active_ids')
        if self.fetch_type == 'to_odoo':
            type_req = 'GET'
            products = self._shopify_get_product_list(active_ids)
            for item in products:
                try:
                    marketplace_instance_id = self.instance_id
                    url = "/inventory_levels.json"
                    headers = {'X-Service-Key': marketplace_instance_id.token}
                    mapping = self.env['shopify.product.mappings'].search([('product_id', '=', item.id), ('shopify_instance_id', '=', marketplace_instance_id.id)], limit=1)
                    if not mapping:
                        return
                    params = {"inventory_item_ids": mapping.shopify_inventory_id}
                    stock_item, next_link = Connector.shopify_api_call(
                        headers=headers,
                        url=url,
                        type=type_req,
                        marketplace_instance_id=marketplace_instance_id,
                        params=params
                    )
                    if stock_item.get('errors'):
                        raise UserError(stock_item.get('errors'))
                    if stock_item.get('inventory_levels'):
                        inventory_stocks = stock_item.get('inventory_levels')
                        for stocks_info in inventory_stocks:
                            self.change_product_qty(stocks_info, item)

                except Exception as e:
                    _logger.warning(e)
                    raise UserError(e)

            return {
                'type': 'ir.actions.client',
                'tag': 'reload'
            }
        elif self.fetch_type == 'from_odoo':
            products = self._shopify_get_product_list(active_ids)
            msg = ''
            for product in products:
                mapping = self.env['shopify.product.mappings'].search([('product_id', '=', product.id), ('shopify_instance_id', '=', self.instance_id.id)], limit=1)
                if not mapping:
                    continue
                try:
                    # if not self.source_location_ids:
                    #     # Update stock for all locations
                    #     mapped_locations = self.env['stock.location'].search([('shopify_location_id', '!=', False)])
                    #     self.source_location_ids = mapped_locations
                    # for location in self.source_location_ids:
                    if self.warehouse_id:
                        if mapping.shopify_id and mapping.shopify_inventory_id:
                            try:
                                update_qty = self._shopify_update_qty(
                                    warehouse=self.warehouse_id.shopify_location_id.shopify_invent_id,
                                    inventory_item_id=mapping.shopify_inventory_id, quantity=int(
                                        product.with_context({"warehouse": self.warehouse_id.id}).free_qty),
                                    marketplace_instance_id=mapping.shopify_instance_id)
                                product.message_post(
                                    body='Product {} ({}) updated {} quantity from {} to location {} of store {}.\n'.format(
                                        product.name, product.default_code, product.with_context(
                                            {"warehouse": self.warehouse_id.id}).free_qty, self.warehouse_id.name,
                                        self.warehouse_id.shopify_location_id.shopify_loc_name, mapping.shopify_instance_id.name))
                            except Exception as e:
                                _logger.warning("Error in Request: %s" % e.args)
                                product.message_post(body=e)
                                continue
                except Exception as e:
                    _logger.warning("Error in Request: %s" % (e.args))
                    raise ValidationError(e)
            return {
                'type': 'ir.actions.client',
                'tag': 'reload'
            }

    def shopify_update_price_item(self):
        Connector = self.env['marketplace.connector']
        active_ids = self._context.get('active_ids')
        products = self._shopify_get_product_list(active_ids)
        msg = ''
        for product in products:
            time.sleep(1)
            if self.instance_id:
                marketplace_instance_id = self.instance_id
                if not marketplace_instance_id.set_price:
                    raise ValidationError('This Shopify Instance is not allowed to update price. Please go to the configuration and turn on this option')
                headers = {
                    'X-Service-Key': marketplace_instance_id.token,
                }
                try:
                    if marketplace_instance_id.set_price:
                        variant = {"id": product.shopify_id}
                        type_req = 'PUT'
                        price = product.lst_price
                        variant.update({"price": price, "compare_at_price": product.product_tmpl_id.shopify_compare_price})
                        data = {'variant': variant}
                        product_url = "/variants/%s.json" % product.shopify_id
                        stock_item, next_link = Connector.shopify_api_call(
                            headers=headers,
                            url=product_url,
                            type=type_req,
                            data=data,
                            marketplace_instance_id=marketplace_instance_id,
                        )
                        if 'call_button' in str(request.httprequest) and stock_item.get('errors'):
                            errors = stock_item.get('errors', {})
                            _logger.warning(_("Request Error: %s" % errors))
                            product.message_post(
                                body='Request Error: %s' % errors)
                            product.product_tmpl_id.message_post(
                                body='%s Request Error: %s' % (product.name, errors))
                        else:
                            product.message_post(
                                body='Product {} ({}) updated price {} on store {}.\n'.format(
                                    product.name, product.default_code, price, marketplace_instance_id.name))
                            product.product_tmpl_id.message_post(
                                body='Product {} ({}) updated price {} on store {}.\n'.format(
                                    product.name, product.default_code, price, marketplace_instance_id.name))
                        product.action_update_shopify_cost_product(marketplace_instance_id)
                except Exception as e:
                    _logger.warning("Error in Request: %s" % e.args)
                    continue

    def change_product_qty(self, stock_info, product_info):
        # location = self.env['stock.location'].search([("shopify_invent_id", "=", stock_info.get("location_id"))], limit=1)
        warehouse = self.env['stock.warehouse'].search(
            [("shopify_invent_id", "=", stock_info.get("location_id"))],
            limit=1)
        if warehouse:
            self.env['stock.quant'].with_context(inventory_mode=True).create({
                'product_id': product_info.id,
                # 'location_id': location.id,
                'location_id': warehouse.lot_stock_id.id,
                'inventory_quantity': stock_info.get('available'),
            }).action_apply_inventory()
        else:
            product_info.message_post(body='Cannot find location that is mapped to shopify location id: {}'.format(stock_info.get("location_id")))
            _logger.warning('Cannot find location that is mapped to shopify location id: {}'.format(stock_info.get("location_id")))
            # raise UserError('Cannot find location that is mapped to shopify location id: {}'.format(stock_info.get("location_id")))

    def _shopify_update_qty(self, **kwargs):
        Connector = self.env['marketplace.connector']

        data = {
            "location_id": kwargs['warehouse'],
            "inventory_item_id": kwargs['inventory_item_id'],
            "available": kwargs['quantity']
        }

        headers = {
            'X-Service-Key': kwargs["marketplace_instance_id"].token,
        }

        type_req = 'POST'
        product_url = '/inventory_levels/set.json'

        stock_item, next_link = Connector.shopify_api_call(
            headers=headers,
            url=product_url,
            type=type_req,
            data=data,
            marketplace_instance_id=kwargs["marketplace_instance_id"],
        )
        _logger.info("stock_item: %s" % stock_item)
        if 'call_button' in str(request.httprequest) and stock_item.get('errors'):
            errors = stock_item.get('errors', {})
            raise Exception(errors)

    def _shopify_adjust_qty(self, **kwargs):
        Connector = self.env['marketplace.connector']

        data = {
            "location_id": kwargs['warehouse'],
            "inventory_item_id": kwargs['inventory_item_id'],
            "available_adjustment": kwargs['quantity']
        }

        headers = {
            'X-Service-Key': kwargs["marketplace_instance_id"].token,
        }

        type_req = 'POST'

        product_url = "/inventory_levels/adjust.json"

        stock_item, next_link = Connector.shopify_api_call(
            headers=headers,
            url=product_url,
            type=type_req,
            data=data,
            marketplace_instance_id=kwargs["marketplace_instance_id"]
        )
        _logger.info("stock_item: %s" % stock_item)
        if 'call_button' in str(request.httprequest) and stock_item.get('errors'):
            errors = stock_item.get('errors', {})
            raise Exception(errors)

    def _shopify_get_product_list(self, active_ids):
        # if self._context.get('active_model') == 'product.product':
        #     products = self.env['product.product'].search([
        #         ('marketplace_type', '=', 'shopify'),
        #         ('id', 'in', active_ids),
        #         ('shopify_id', 'not in', ['', False])
        #     ])
        # if self._context.get('active_model') == 'product.template':
        #     products = self.env['product.product'].search([
        #         ('marketplace_type', '=', 'shopify'),
        #         ('product_tmpl_id', 'in', active_ids),
        #         ('shopify_id', 'not in', ['', False])
        #     ])
        mappings = False
        if self._context.get('active_model') == 'product.product':
            mappings = self.env['shopify.product.mappings'].search([('product_id', 'in', active_ids), ('shopify_instance_id', '=', self.instance_id.id)])
        if self._context.get('active_model') == 'product.template':
            mappings = self.env['shopify.product.mappings'].search([('product_tmpl_id', 'in', active_ids), ('shopify_instance_id', '=', self.instance_id.id)])
        return mappings.product_id

    def ir_cron_need_sync_stock(self, warehouse_id=None, instance_id=None):
        if not warehouse_id or not instance_id:
            return
        warehouse = self.env['stock.warehouse'].browse(warehouse_id)
        products = self.env['product.product'].search([('shopify_need_sync', '=', True)])
        for product in products:
            mapping = self.env['shopify.product.mappings'].search([('product_id', '=', product.id), ('shopify_instance_id', '=', instance_id)])
            try:
                self._shopify_update_qty(
                    warehouse=warehouse.shopify_location_id.shopify_invent_id,
                    inventory_item_id=mapping.shopify_inventory_id, quantity=int(
                        product.with_context({"warehouse": warehouse_id}).free_qty),
                    marketplace_instance_id=mapping.shopify_instance_id)
                product.shopify_need_sync = False
            except Exception as e:
                _logger.info(e)
