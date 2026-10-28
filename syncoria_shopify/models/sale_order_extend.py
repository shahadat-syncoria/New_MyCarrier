# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

from odoo import models, fields, exceptions, api, _
import requests
import logging
_logger = logging.getLogger(__name__)


class SaleOrderSExtend(models.Model):
    _inherit = 'sale.order'

    def fix_delivery_address(self):
        res_country = self.env['res.country'].sudo()
        res_country_state = self.env['res.country.state'].sudo()
        if self.shopify_instance_id and self.shopify_id:
            base_url = self.shopify_instance_id.marketplace_host
            base_url = base_url[0:-1] if base_url[-1] == '/' else base_url
            base_url = 'https://' + base_url if not 'http' in base_url else base_url
            api_version = self.shopify_instance_id.marketplace_api_version
            endpoint = '/admin/api/{}/orders/{}.json'.format(api_version, self.shopify_id)
            url = base_url + endpoint
            headers = {'X-Shopify-Access-Token': self.shopify_instance_id.marketplace_api_password}
            res = requests.request(method='GET', url=url, headers=headers)

            _logger.info("URL ===>>>{}".format(url))
            _logger.info("res ===>>>{}".format(res))
            _logger.info("status_code ===>>>{}".format(res.status_code))

            if res.status_code == 200:
                sp_order_dict = res.json()
                if sp_order_dict.get('order'):
                    _logger.info("sp_order_dict ===>>>{}".format(sp_order_dict))
                    sp_order_dict = sp_order_dict.get('order')
                    partner_id = self.partner_id
                    partner_invoice_id = self.partner_invoice_id
                    partner_shipping_id = self.partner_shipping_id
                    
                    if sp_order_dict.get('contact_email'):
                        parner_vals = {
                            'email': sp_order_dict.get('contact_email') or sp_order_dict.get('email'),
                            'phone': sp_order_dict.get('phone'),
                        }
                        partner_id.write(parner_vals)


                    if sp_order_dict.get('billing_address'):
                        billing_address = sp_order_dict.get('billing_address', {})

                        if partner_invoice_id:
                            country_id = self.env['res.country'].sudo()
                            state_id = self.env['res.country.state'].sudo()

                            if billing_address.get('country'):
                                bill_country = billing_address.get('country')
                                country_domain = [('name', '=', bill_country)]
                                country_id = res_country.search(country_domain, limit=1)

                            if billing_address.get('province'):
                                state_domain = [('country_id', '=', country_id.id)] if country_id else []
                                state_domain += [('name', '=', billing_address.get('province'))]
                                state_id = res_country_state.search(state_domain, limit=1)

                            partner_invoice_id.write({
                                'name': billing_address.get('name', None),
                                'street': billing_address.get('address1'),
                                'street2': billing_address.get('address2'),
                                'city': billing_address.get('city'),
                                'zip': billing_address.get('zip'),
                                'state_id': state_id.id,
                                'country_id': country_id.id,
                                'phone': billing_address.get('phone'),
                            })

                    if sp_order_dict.get('shipping_address'):
                        shipping_address = sp_order_dict.get('shipping_address', {})

                        if partner_shipping_id:
                            country_id = self.env['res.country'].sudo()
                            state_id = self.env['res.country.state'].sudo()

                            if shipping_address.get('country'):
                                bill_country = shipping_address.get('country')
                                country_domain = [('name', '=', bill_country)]
                                country_id = res_country.search(country_domain, limit=1)

                            if shipping_address.get('province'):
                                state_domain = [('country_id', '=', country_id.id)] if country_id else []
                                state_domain += [('name', '=', shipping_address.get('province'))]
                                state_id = res_country_state.search(state_domain, limit=1)

                            partner_shipping_id.write({
                                'name': shipping_address.get('name', None),
                                'street': shipping_address.get('address1'),
                                'street2': shipping_address.get('address2'),
                                'city': shipping_address.get('city'),
                                'zip': shipping_address.get('zip'),
                                'state_id': state_id.id,
                                'country_id': country_id.id,
                                'phone': billing_address.get('phone'),
                            })

                else:
                    error = """No Shopify Order Found"""
                    _logger.warning(error)
            else:
                error = """Error {}""".format(res.text)
                _logger.warning(error)
        else:
            error = "shopify_instance_id or shopify_id are missing for SO-{}".format(self.name)
            _logger.warning(error)