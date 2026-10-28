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

_logger = logging.getLogger(__name__)


def intersection(lst1, lst2):
    lst3 = [value for value in lst1 if value in lst2]
    return lst3


class OrderFetchWizard(models.TransientModel):
    _inherit = 'order.fetch.wizard'

    order_status = fields.Selection(selection_add=[
            ('any', 'All'),
            ('open', 'Opened'),
            ('closed', 'Closed'),
            ('cancelled', 'Cancelled')
        ], string="Order Status",default='any')
    fetch_all_order = fields.Boolean('Fetch All Order')
    shopify_order_no = fields.Char()
    feed_only = fields.Boolean(string='Fetch Feed Order only', default=False)

    def fetch_query(self, vals):
        """constructing the query, from the provided column names"""
        query_str = ""
        if not vals:
            return
        for col in vals:
            query_str += " " + str(col) + ","
        return query_str[:-1]

    def cron_shopify_fetch_orders(self,instance_id):
        wizard_id = False
        try:
            if instance_id:
                instance_id = self.env['marketplace.instance'].browse(instance_id)
            else:
                instance_id = self.env['marketplace.instance'].search([], limit=1)

            wizard_id = self.create({'instance_id': instance_id.id, 'date_from': fields.Date.today(), 'date_to': fields.Date.today()})
        except Exception as e:
            log_id = self.env['marketplace.logging'].sudo().create({
                'name': self.env['ir.sequence'].next_by_code('marketplace.logging'),
                'create_uid': self.env.user.id,
                # 'marketplace_instance_id': self.instance_id.id,
                'level': 'warning',
                'type': 'client',
                'summary': ''.replace('<br>', '').replace('</br>', '\n'),
                'error': str(e).replace('<br>', '').replace('</br>', '\n'),
            })
        if wizard_id:
            wizard_id.fetch_orders()

    def shopify_fetch_orders(self, kwargs=None):
        """Function to Fetch Orders From Shopify

        Args:
            kwargs (dict, marketplace_instance_id): Dictionary. Marketplace Instance ID.

        Returns:
            action: Action
        """

        marketplace_instance_id = kwargs.get("marketplace_instance_id") or self.instance_id

        url = '/orders.json'
        update_url = '/orders.json'

        # Request Parameters
        type_req = 'GET'
        params = {
            "limit": 250,
            "status": "any"
        }
        try:
            if self.order_status:
                params.update({"status": self.order_status})
        except Exception as e:
            _logger.info("Exception- {}".format(e.args))

        headers = {'X-Service-Key': marketplace_instance_id.token}

        orders_list = []
        orders_created_list = []
        orders_updated_list = []

        tz_offset = '-00:00'
        if self.env.user and self.env.user.tz_offset:
            tz_offset = self.env.user.tz_offset
        ###################################################################
        # FETCH CREATED ORDERS: Starts######################################
        ###################################################################
        if not self.shopify_order_no:
            if self.date_from and not self.date_to:
                url += '?created_at_min=%s' % self.date_from.strftime(
                    "%Y-%m-%dT00:00:00" + tz_offset)
            if not self.date_from and self.date_to:
                url += '?created_at_max=%s' % self.date_to.strftime(
                    "%Y-%m-%dT23:59:59" + tz_offset)
            if self.date_from and self.date_to:
                url += '?created_at_min=%s' % self.date_from.strftime(
                    "%Y-%m-%dT00:00:00" + tz_offset)
                url += '&created_at_max=%s' % self.date_to.strftime(
                    "%Y-%m-%dT23:59:59" + tz_offset)
            if not self.date_from and not self.date_to:
                # url += '?created_at_min=%s' % fields.Datetime.now().strftime(
                #     "%Y-%m-%dT00:00:00" + tz_offset)
                # url += '&created_at_max=%s' % fields.Datetime.now().strftime(
                #     "%Y-%m-%dT23:59:59" + tz_offset)
                url = '/orders.json'
        else:
            url = '/orders/%s.json' % self.shopify_order_no if self.shopify_order_no else url

        while True:
            created_orders, next_link = self.env['marketplace.connector'].shopify_api_call(
                headers=headers,
                url=url,
                type=type_req,
                marketplace_instance_id=marketplace_instance_id,
                params=params)
            try:
                if created_orders.get('orders'):
                    orders_created_list += created_orders['orders'] if created_orders.get('orders') else []
                if created_orders.get('order'):
                    orders_created_list += [created_orders['order']] if created_orders.get('order') else []

                if next_link:
                    if next_link.get("next"):
                        full_url = next_link.get("next").get("url")
                        """
                            The pagination url contains the full url so we have to split the string
                        """
                        full_url_arr_split = full_url.split('/')
                        url = '/' + full_url_arr_split[-1]
                        if params.get('status'):
                            del (params['status'])
                        if params.get('limit'):
                            del (params['limit'])
                    else:
                        break
                else:
                    break
            except Exception as e:
                _logger.info("Exception occured: %s", e)
                raise exceptions.UserError(_("Error Occured %s") % e)

        if url and orders_created_list:
            _logger.info("\nurl >>>>>>>>>>>>>>>>>>>>>>" + str(url) +
                         "\nOrder #:--->" + str(len(orders_created_list)))

        ###################################################################
        # FETCH CREATED ORDERS: Ends########################################
        ###################################################################

        ###################################################################
        # FETCH UPDATED ORDERS: Starts######################################
        ###################################################################
        params.update({"status": "any"})
        try:
            if self.order_status:
                params.update({"status": self.order_status})
        except Exception as e:
            params.update({"status": "any"})

        if not self.shopify_order_no:
            if self.date_from and not self.date_to:
                update_url += '?updated_at_min=%s' % self.date_from.strftime(
                    "%Y-%m-%dT00:00:00" + tz_offset)
            if not self.date_from and self.date_to:
                update_url += '?updated_at_max=%s' % self.date_to.strftime(
                    "%Y-%m-%dT23:59:59" + tz_offset)
            if self.date_from and self.date_to:
                update_url += '?updated_at_min=%s' % self.date_from.strftime(
                    "%Y-%m-%dT00:00:00" + tz_offset)
                update_url += '&updated_at_max=%s' % self.date_to.strftime(
                    "%Y-%m-%dT23:59:59" + tz_offset)
            if not self.date_from and not self.date_to:
                update_url += '?updated_at_min=%s' % fields.Datetime.now().strftime(
                    "%Y-%m-%dT00:00:00" + tz_offset)
                update_url += '&updated_at_max=%s' % fields.Datetime.now().strftime(
                    "%Y-%m-%dT23:59:59" + tz_offset)
        else:
            update_url = '/orders/%s.json' % self.shopify_order_no if self.shopify_order_no else url
        _logger.info("update_url===>>>>{}".format(update_url))

        while True and not self.shopify_order_no:
            updated_orders, next_link = self.env['marketplace.connector'].shopify_api_call(
                headers=headers,
                url=update_url,
                type=type_req,
                marketplace_instance_id=marketplace_instance_id,
                params=params)
            try:
                orders_updated_list += updated_orders['orders'] if updated_orders.get('orders') else []
                orders_updated_list += [updated_orders['order']] if updated_orders.get('order') else []
                if next_link:
                    if next_link.get("next"):
                        url = next_link.get("next").get("url")
                        if params.get('status'):
                            del (params['status'])

                    else:
                        break
                else:
                    break
            except Exception as e:
                _logger.info("Exception occured: %s", e)
                raise exceptions.UserError(_("Error Occured %s") % e)

        if url and orders_updated_list:
            _logger.info("\nurl >>>>>>>>>>>>>>>>>>>>>>" + str(url) +
                         "\nOrder #:--->" + str(len(orders_updated_list)))
        ###################################################################
        # FETCH UPDATED ORDERS: Ends########################################
        ###################################################################

        orders_created_ids = [order['id'] for order in orders_created_list]
        orders_updated_ids = [order['id'] for order in orders_updated_list]
        orders_common = intersection(orders_created_ids, orders_updated_ids)

        orders_list = [order for order in orders_created_list if order['id'] not in orders_common]
        if orders_updated_ids:
            orders_list += orders_updated_list

        order_list = {"orders": orders_list}

        _logger.info("url===>>>>{}".format(url))
        _logger.info("update_url===>>>>{}".format(update_url))
        _logger.info("Order #==>>>>{}".format(len(order_list.get('orders'))))

        try:
            log_msg = ''
            error_msg = ''
            sp_orders = order_list['orders']

            feed_order_list = []
            for i in sp_orders:
                created_at_date = datetime.datetime.fromisoformat(i.get("created_at")).date()
                if created_at_date>=datetime.datetime(2024, 2, 9, 0, 0, 0).date():
                    feed_order_id, feed_log_msg, feed_error_msg = self.create_feed_orders(i)
                    feed_order_list += feed_order_id.ids
                    log_msg += feed_log_msg
                    error_msg += feed_error_msg
                    if not self.feed_only:
                        process_log_msg, process_error_msg = feed_order_id.process_feed_order()
                        log_msg += process_log_msg
                        error_msg += process_error_msg

            try:
                if feed_order_list and self.instance_id:
                    log_id = self.env['marketplace.logging'].sudo().create({
                        'name': self.env['ir.sequence'].next_by_code('marketplace.logging'),
                        'create_uid': self.env.user.id,
                        'marketplace_instance_id': self.instance_id.id,
                        'level': 'info',
                        'summary': log_msg.replace('<br>', '').replace('</br>', '\n'),
                        'error': error_msg.replace('<br>', '').replace('</br>', '\n'),
                    })
                    log_id._cr.commit()
            except Exception as e:
                _logger.exception("Exception-{}".format(e.args))


        except Exception as e:
            _logger.warning("Exception occured %s", e)
            raise exceptions.UserError(_("Error Occured:\n %s") % e)

        #################################################################################
        ######Fetch Not Processed Order and Process Them#################################
        #################################################################################
        # try:
        #     sp_feed_order = self.env['shopify.feed.orders'].sudo()
        #     unprocessed_orders = sp_feed_order.search([('state', '=', 'draft')])
        #
        #     for feed_order in unprocessed_orders:
        #         feed_order.fetch_shopify_order()
        #         feed_order.process_feed_order()
        #         feed_order._cr.commit()
        except Exception as e:
            _logger.warning("Exception occured %s", e)

        # if 'call_button' in str(request.httprequest):
        #     return {
        #         'name': ('Shopify Orders'),
        #         'type': 'ir.actions.act_window',
        #         'view_type': 'form',
        #         'view_mode': 'tree,form',
        #         'res_model': 'sale.order',
        #         'view_id': False,
        #         'domain': [('marketplace_type', '=', 'shopify')],
        #         'target': 'current',
        #     }
        # else:
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'reload'
        #     }

    def create_feed_orders(self, order_data):
        log_msg = ''
        error_msg = ''
        feed_order_id = False
        try:
            marketplace_instance_id = self.instance_id
            customer_first_name = order_data.get('customer', {}).get('first_name', '') if order_data.get('customer',
                                                                                                         {}).get(
                'first_name', '') else ''
            customer_last_name = order_data.get('customer', {}).get('last_name', '') if order_data.get('customer',
                                                                                                       {}).get(
                'last_name', '') else ''
            customer_name = customer_first_name + ' ' + customer_last_name
            domain = [('shopify_id', '=', order_data['id'])]
            domain += [('instance_id', '=', marketplace_instance_id.id)]
            feed_order_id = self.env['shopify.feed.orders'].sudo().search(domain, limit=1)
            if not feed_order_id:
                feed_order_id = self.env['shopify.feed.orders'].sudo().create({
                    'name': self.env['ir.sequence'].sudo().next_by_code('shopify.feed.orders'),
                    'instance_id': marketplace_instance_id.id,
                    'shopify_id': order_data['id'],
                    'order_data': json.dumps(order_data),
                    'state': 'draft',
                    'shopify_webhook_call': False,
                    'shopify_app_id': order_data.get('app_id'),
                    'shopify_confirmed': order_data.get('confirmed'),
                    'shopify_contact_email': order_data.get('contact_email'),
                    'shopify_currency': order_data.get('currency'),
                    'shopify_customer_name': customer_name,
                    'shopify_customer_id': order_data.get('customer', {}).get('id', ''),
                    'shopify_gateway': order_data.get('gateway'),
                    'shopify_order_number': order_data.get('order_number'),
                    'shopify_financial_status': order_data.get('financial_status'),
                    'shopify_fulfillment_status': order_data.get('fulfillment_status'),
                    'shopify_line_items': len(order_data.get('line_items')),
                    'shopify_user_id': order_data.get('user_id'),
                })

                msg = _("Shopify Feed Order Created-{}".format(feed_order_id))
                _logger.info(msg)
                log_msg += "<br>" + msg + "</br>"
            else:
                feed_order_id.write({
                    'order_data': json.dumps(order_data),
                    'shopify_app_id': order_data.get('app_id'),
                    'shopify_confirmed': order_data.get('confirmed'),
                    'shopify_contact_email': order_data.get('contact_email'),
                    'shopify_currency': order_data.get('currency'),
                    'shopify_customer_name': customer_name,
                    'shopify_customer_id': order_data.get('customer', {}).get('id', ''),
                    'shopify_gateway': order_data.get('gateway'),
                    'shopify_order_number': order_data.get('order_number'),
                    'shopify_financial_status': order_data.get('financial_status'),
                    'shopify_fulfillment_status': order_data.get('fulfillment_status'),
                    'shopify_line_items': len(order_data.get('line_items')),
                    'shopify_user_id': order_data.get('user_id'),
                })

                msg = _("\nShopify Feed Order Updated-{}".format(feed_order_id))
                _logger.info(msg)
                log_msg += "<br>" + msg + "</br>"

            # feed_order_id._cr.commit()
        except Exception as e:
            error_msg += '<br> Shopify Order Feed Order Creation: {} Exception-{} </br>'.format(
                order_data.get('order_number'), e.args)
        return feed_order_id, log_msg, error_msg

    # def _get_inv_vals(self, order_id, sp_order):
    #     inv_vals = {}
    #     mkplc_id = self._get_instance_id()
    #     inv_vals.update({
    #         "ref": "",
    #         "move_type": "out_invoice",
    #         "narration": "",
    #         "currency_id": order_id.currency_id.id,
    #         "campaign_id": order_id.campaign_id.id,
    #         "medium_id": order_id.medium_id.id,
    #         "source_id": order_id.source_id.id,
    #         "user_id": order_id.user_id.id,
    #         "invoice_user_id": order_id.user_id.id,
    #         "team_id": order_id.team_id.id,
    #         "partner_id": order_id.partner_id.id,
    #         "partner_shipping_id": order_id.partner_shipping_id.id,
    #         "fiscal_position_id": order_id.fiscal_position_id.id,
    #         # "partner_bank_id": order_id.partner_bank_id.id,
    #         "journal_id": mkplc_id.marketplace_journal_id.id,
    #         "invoice_origin": order_id.name,
    #         "invoice_payment_term_id": mkplc_id.payment_term_id.id,
    #         "payment_reference": False,
    #         "transaction_ids": [(6, 0, [])],
    #         "company_id": order_id.company_id.id,
    #         "invoice_incoterm_id": False
    #     })
    #     inv_vals['invoice_line_ids'] = []
    #
    #     for line in order_id.order_line:
    #         #####################################################################################
    #         #TO DO: Compute Price from Pricelist
    #         #####################################################################################
    #         inv_vals['invoice_line_ids'].append(
    #             (0, 0,
    #              {
    #                  "display_type": False,
    #                  "sequence": 0,
    #                  "name": line.name,
    #                  "product_id": line.product_id.id,
    #                  "product_uom_id": line.product_id.uom_id.id,
    #                  "quantity": line.product_qty,
    #                  "discount": line.discount,
    #                  "price_unit": line.price_unit,
    #                  "tax_ids": [(6, 0, line.tax_id.ids)],
    #                  "analytic_account_id": False,
    #                  "analytic_tag_ids": [(6, 0, [])],
    #                  "sale_line_ids": [(4, 81)]
    #              })
    #         )
    #
    #     self.env['account.move'].sudo().create(inv_vals)


    def _shopify_get_ship(self, ship_line, ma_ins_id):
        ship_value = {}
        ship_value['name'] = ship_line.get('title')
        ship_value['sale_ok'] = False
        ship_value['purchase_ok'] = False
        ship_value['type'] = 'service'
        ship_value['default_code'] = ship_line.get('code')
        categ_id = self.env['product.category'].sudo().search(
            [('name', '=', 'Deliveries')], limit=1)
        ship_value['categ_id'] = categ_id.id
        ship_value['company_id'] = ma_ins_id.company_id.id
        ship_value['responsible_id'] = ma_ins_id.user_id.id
        return ship_value

    def shopify_push_tracking(self):
        SaleOrder = self.env['sale.order'].sudo()
        StkPicking = self.env['stock.picking'].sudo()
        marketplace_instance_id = self._get_instance_id()
        current_date = fields.Datetime.now()
        _logger.info("current_date#===>>>" + str(current_date))
        start_date = current_date.replace(
            hour=0, minute=0, second=0, microsecond=0)
        end_date = current_date.replace(
            hour=23, minute=59, second=59, microsecond=999999)
        _logger.info("start_date#===>>>" + str(start_date))
        _logger.info("end_date#===>>>" + str(end_date))
        log_msg = ''

        if marketplace_instance_id.marketplace_instance_type == 'shopify':
            sale_domain = [('state', 'in', ('sale', 'done')),
                           ('shopify_track_updated', '=', False),
                           ('date_order', '>=', start_date),
                           ('date_order', '<=', end_date)
                           ]
            sale_ids = SaleOrder.search(sale_domain)

            _logger.info("Sale#===>>>" + str(sale_ids))
            for sale_id in sale_ids:
                """Step: 1. Find all Pickings for sale Order"""
                pick_domain = [
                    ('state', '=', 'done'),
                    ('shopify_track_updated', '=', False),
                    ('origin', '=', sale_id.name)]
                pickings = StkPicking.search(pick_domain)
                _logger.info("pickings#===>>>" + str(pickings))
                """Step: 2. If Picking == 1: Update Tracking Number"""
                if len(pickings) == 1:
                    msg = _("Push Tracking for Sale Order-%s, Picking-%s Starts" %
                            (sale_id.name, pickings.name))
                    _logger.info(msg)
                    log_msg += "\n" + msg
                    response = pickings.create_shopify_fulfillment()
                    msg = _("Push Tracking for Sale Order-%s, Picking-%s Ends" %
                            (sale_id.name, pickings.name))
                    _logger.info(msg)
                    log_msg += "\n" + msg
                """Step: 2. If Picking  > 1: Do nothing"""
                if len(pickings) > 1:
                    msg = _("Tracking cannot be updated for Sale Order-%s" %
                            (sale_id.name))
                    _logger.warning(msg)
                    log_msg += "\n" + msg


    def _process_customer_addresses(self, partner_id, item):
        vals = {}
        if type(item['addresses']) == dict:
            if item.get('addresses'):
                for address in item.get('addresses'):
                    if address.get('default') and partner_id.type == 'invoice':
                        partner_id.write({
                            'shopify_default': True,
                            'shopify_add_id': address.get('id'),
                        })
                    if address.get('default') == False:
                        domain = [('shopify_add_id', '=', address.get('id'))]
                        res_partner = self.env['res.partner']
                        part_id = res_partner.sudo().search(domain, limit=1)
                        if not part_id:
                            add_vals = get_address_vals(self.env, address)
                            add_vals['type'] = 'other'
                            add_vals['parent_id'] = partner_id.id
                            add_vals['property_account_receivable_id'] = partner_id.property_account_receivable_id.id
                            add_vals['property_account_payable_id'] = partner_id.property_account_payable_id.id

                            res_partner.sudo().create(add_vals)
        elif type(item.get('addresses')) == list:
            for address in item['addresses']:
                if address.get('default') and partner_id.type == 'invoice':
                    partner_id.write({
                        'shopify_default': True,
                        'shopify_add_id': address.get('id'),
                    })
                if address.get('default') == False:
                    domain = [('shopify_add_id', '=', address.get('id'))]
                    res_partner = self.env['res.partner']
                    part_id = res_partner.sudo().search(domain, limit=1)
                    if not part_id:
                        add_vals = get_address_vals(self.env, address)
                        add_vals['type']='other'
                        add_vals['parent_id'] = partner_id.id
                        add_vals['property_account_receivable_id'] = partner_id.property_account_receivable_id.id
                        add_vals['property_account_payable_id'] = partner_id.property_account_payable_id.id
                        res_partner.sudo().create(add_vals)

        return vals
