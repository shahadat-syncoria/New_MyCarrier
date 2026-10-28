# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################
import json
import requests
import logging
import base64
import re
from odoo import models, fields, exceptions, _
from odoo.exceptions import UserError, ValidationError

from odoo.http import request
from pprint import pprint

_logger = logging.getLogger(__name__)


class ProductsFetchWizard(models.TransientModel):
    _inherit = 'products.fetch.wizard'
    shopify_product_id = fields.Char(string='Shopify product ID')
    mappings_only = fields.Boolean(string='Mappings Only')
    feed_only = fields.Boolean(string='Fetch Feed product only',default=False)

    def get_product_attribute_id(self, attribute_name):
        attrib_id = self.env['product.attribute'].search(
            [('name', '=', attribute_name)])
        # -------------------------Newly Added---------------------------
        if attribute_name == 'Title' and len(attrib_id) == 0:
            attrib_id = self.env['product.attribute'].sudo().create(
                {
                    'create_variant': 'no_variant',
                    'display_type': 'radio',
                    'name': attribute_name,
                }
            )
        # -------------------------Newly Added---------------------------
        return attrib_id

    def get_product_attribute_value_id(self, attribute_id, product_attribute_id, template_id, attribute_names):
        att_val_id = self.env['product.attribute.value'].search(
            [('attribute_id', 'in', product_attribute_id),
             ('name', 'in', attribute_names),
             ])
        return att_val_id

    def check_for_new_attrs(self, template_id, variant):
        context = dict(self._context or {})
        product_template = self.env['product.template']
        product_attribute_line = self.env['product.template.attribute.line']
        all_values = []
        # attributes = variant.name_value
        attributes = variant

        for attribute in attributes:
            # for attribute_id in eval(attributes):
            attribute_id = attribute.get('name')  # 'Color'
            attribute_names = attribute.get('values')
            product_attribute_id = self.get_product_attribute_id(attribute_id)
            product_attribute_value_id = self.get_product_attribute_value_id(
                attribute_id,
                product_attribute_id.ids,
                template_id,
                attribute_names
            )

            exists = product_attribute_line.search(
                [
                    ('product_tmpl_id', '=', template_id.id),
                    ('attribute_id', 'in', product_attribute_id.ids)
                ]
            )
            if exists:
                pal_id = exists[0]
            else:
                pal_id = product_attribute_line.create(
                    {
                        'product_tmpl_id': template_id.id,
                        'attribute_id': product_attribute_id.id,
                        'value_ids': [[4, product_attribute_value_id]]
                    }
                )

            value_ids = pal_id.value_ids.ids
            for product_attribute_value_id in product_attribute_value_id.ids:
                if product_attribute_value_id not in value_ids:
                    pal_id.write(
                        {'value_ids': [[4, product_attribute_value_id]]})

                    PtAv = self.env['product.template.attribute.value']
                    domain = [
                        ('attribute_id', 'in', product_attribute_id.ids),
                        ('attribute_line_id', '=', pal_id.id),
                        ('product_attribute_value_id',
                         '=', product_attribute_value_id),
                        ('product_tmpl_id', '=', template_id.id)
                    ]

                    attvalue = PtAv.search(domain)

                    if len(attvalue) == 0:
                        product_template_attribute_value_id = PtAv.create({
                            'attribute_id': product_attribute_id.id,
                            'attribute_line_id': pal_id.id,  # attribute_line_id.id,
                            'product_attribute_value_id': product_attribute_value_id,
                            'product_tmpl_id': template_id.id,
                        })

                        all_values.append(
                            product_template_attribute_value_id.id)
        return [(6, 0, all_values)]

    def _shopify_update_attributes(self, odoo_attributes, options, attributes):
        cr = self._cr
        options = [str(i['attribute_id']) for i in options]

        for att in attributes:

            _logger.info("\natt['attribute_code']==>" +
                         str(att['attribute_id']))

            if str(att['attribute_id']) not in odoo_attributes and str(
                    att['attribute_id']) in options:

                # Check Attribureid in database
                print(att['attribute_code'])
                domain = [('name', '=', att['attribute_code'])]
                PA = self.env['product.attribute']
                rec = PA.sudo().search(domain)
                if rec:
                    cr.execute(
                        "select id from product_attribute where id=%s", (rec.id,))
                    rec_id = cr.fetchone()
                else:
                    cr.execute(
                        "insert into product_attribute (name,create_variant,display_type,marketplace_type) "
                        " values(%s, FALSE, 'radio', 'shopify') returning id",
                        (att['attribute_code'],))
                    rec_id = cr.fetchone()
                odoo_attributes[str(att['attribute_id'])] = {
                    'id': rec_id[0],  # id of the attribute in odoo
                    'code': att['attribute_code'],  # label
                    'options': {}
                }

            # attribute values
            if str(att['attribute_id']) in options:
                odoo_att = odoo_attributes[str(att['attribute_id'])]
                for opt in att['options']:
                    if opt != '' and opt != None \
                            and opt not in odoo_att['options']:

                        query = "Select id from product_attribute_value where name='" + opt + "' AND attribute_id='" + \
                                str(odoo_att['id']) + \
                                "' AND marketplace_type='shopify'"
                        cr.execute(query)
                        rec_id = cr.fetchone()

                        if not rec_id:
                            cr.execute(
                                "insert into product_attribute_value (name, attribute_id, marketplace_type)  "
                                "values(%s, %s, 'shopify') returning id",
                                (opt, odoo_att['id']))
                            rec_id = cr.fetchone()

                        # linking id in shopify with id in odoo
                        odoo_att['options'][str(opt)] = rec_id[0]

        return odoo_attributes

    def get_product_data(self):
        catalog_data = []
        products = self.env['product.product'].search([
            ('marketplace_type', '=', 'shopify'),
            ('default_code', '!=', None)
        ])

        if products:
            for product in products:
                product_data = {
                    "sku": product.default_code,
                    "name": product.name,
                    "price": product.list_price,
                    "attribute_set_id": 4,
                    "type_id": "simple"
                }
                catalog_data.append({"product": product_data})
        return catalog_data and [catalog_data, products] or None

    def shopify_fetch_products_to_odoo(self, kwargs):
        update_products_no = 0
        sp_product_list = []
        existing_ids = []
        cr = self._cr
        # fetching products already fetched from shopify to skip those already created
        # cr.execute("select shopify_id from product_template "
        #            "where shopify_id is not null ")
        # products = cr.fetchall()
        # ids = [str(i[0]) for i in products] if products else []
        #
        # cr.execute("select shopify_id from product_product "
        #            "where shopify_id is not null")
        # products = cr.fetchall()
        # for i in products:
        #     ids.append(i[0]) if i[0] not in ids else None

        categ_list = []

        if len(kwargs.get('marketplace_instance_id')) > 0:
            marketplace_instance_id = kwargs.get('marketplace_instance_id')
            url = '/products.json'

            if kwargs.get('fetch_o_product'):
                url = '/products/%s.json' % kwargs.get('product_id')
            tz_offset = '-00:00'
            if self.env.user and self.env.user.tz_offset:
                tz_offset = self.env.user.tz_offset

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

            _logger.info("Product URL-->" + str(url))

            headers = {'X-Service-Key': marketplace_instance_id.token}
            type_req = 'GET'

            params = {"limit": 250}
            products = []
            while True:
                fetched_products, next_link = self.env[
                    'marketplace.connector'].shopify_api_call(
                    headers=headers,
                    url=url,
                    type=type_req,
                    marketplace_instance_id=marketplace_instance_id,
                    params=params
                )
                try:
                    if 'errors' in fetched_products and len(fetched_products['errors']) > 0:
                        raise UserError('Something is wrong. Please make sure the store is configured correctly.')
                    if type(fetched_products).__name__ == 'list':
                        products += fetched_products['products']
                    elif type(fetched_products).__name__ == 'dict':
                        products += fetched_products.get('products') or [fetched_products.get('product')]
                    else:
                        products += [fetched_products['product']]

                    if next_link:
                        if next_link.get("next"):
                            full_url = next_link.get("next").get("url")
                            """
                                The pagination url contains the full url so we have to split the string
                            """
                            full_url_arr_split = full_url.split('/')
                            url = '/' + full_url_arr_split[-1]
                            if 'limit' in params:
                                del params['limit']
                        else:
                            break
                    else:
                        break
                except Exception as e:
                    _logger.warning("Exception occurred: %s", e)
                    raise exceptions.UserError(_("Error Occurred %s") % e)
            _logger.info("Product fetch done: %s", len(products))
            if not kwargs.get('fetch_o_product', False):
                updated_products = []
                update_url = '/products.json'
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
                while True:
                    fetched_products, next_link = self.env[
                        'marketplace.connector'].shopify_api_call(
                        headers=headers,
                        url=update_url,
                        type=type_req,
                        marketplace_instance_id=marketplace_instance_id,
                        params=params
                    )
                    try:
                        if 'errors' in fetched_products and len(fetched_products['errors']) > 0:
                            raise UserError('Something is wrong. Please make sure the store is configured correctly.')
                        if type(fetched_products).__name__ == 'list':
                            updated_products += fetched_products['products']
                        elif type(fetched_products).__name__ == 'dict':
                            updated_products += fetched_products.get('products') or [fetched_products.get('product')]
                        else:
                            updated_products += [fetched_products['product']]

                        if next_link:
                            if next_link.get("next"):
                                full_url = next_link.get("next").get("url")
                                """
                                    The pagination url contains the full url so we have to split the string
                                """
                                full_url_arr_split = full_url.split('/')
                                url = '/' + full_url_arr_split[-1]
                                if 'limit' in params:
                                    del params['limit']
                            else:
                                break
                        else:
                            break
                    except Exception as e:
                        _logger.info("Exception occurred: %s", e)
                        raise exceptions.UserError(_("Error Occurred %s") % e)

                created_product_id = [prod.get('id') for prod in products]
                for prod in updated_products:
                    if prod['id'] not in created_product_id:
                        products += [prod]
            if type(products).__name__ == 'list':
                configurable_products = {"products": products}
            else:
                configurable_products = fetched_products


            # Update Product Categories
            # in shopify, each product can have one product type(category), so we are fetching all the product types
            # from shopify
            # and creating those in odoo. For the products updated from shopify,
            # we will be showing all the shopify categories in a separate field
            try:
                if kwargs.get('mappings_only'):
                    for product in configurable_products['products']:
                        for variant in product['variants']:
                            product_id = False
                            mapping_id = self.env['shopify.product.mappings'].search(
                                [('shopify_id', '=', variant['id']),
                                 ('shopify_instance_id', '=', marketplace_instance_id.id)])
                            if mapping_id and mapping_id.product_id:
                                # product_id = self.env['product.product'].search([('default_code', '=', variant['sku'])], limit=1)
                                product_id = mapping_id.product_id
                            if marketplace_instance_id.is_sku and not product_id:
                                product_id = self.env['product.product'].search([('default_code', '=', variant['sku'])], limit=1)

                            if product_id:
                                vals = {
                                    'product_id': product_id.id,
                                    'shopify_instance_id': marketplace_instance_id.id,
                                    'name': variant['sku'],
                                    'shopify_id': variant['id'],
                                    'shopify_parent_id': variant['product_id'],
                                    'shopify_inventory_id': variant['inventory_item_id']
                                }
                                mapping_id = self.env['shopify.product.mappings'].search([('shopify_id', '=', variant['id']), ('shopify_instance_id', '=', marketplace_instance_id.id)])
                                if not mapping_id:
                                    self.env['shopify.product.mappings'].create(vals)
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    }
                if configurable_products.get('errors'):
                    errors = configurable_products.get('errors')
                    _logger.warning("Exception occured: {}".format(errors))
                    raise exceptions.UserError(_("Error Occured {}".format(errors)))
                if configurable_products.get('products'):
                    product_list = configurable_products.get('products')
                else:
                    product_list = [configurable_products.get('product')] if type(configurable_products.get('products')) != list else configurable_products.get('products')

                all_feed_products_rec = [self.create_feed_parent_product(product,marketplace_instance_id) for product in product_list]
                if not self.feed_only:
                    for process_product in all_feed_products_rec:
                        update_products_no += 1
                        process_product.process_feed_product()
                        process_product.write({"state":'processed'})

            except Exception as e:
                _logger.warning("Exception occured: {}".format(e.args))
                raise exceptions.UserError(_("Error Occured %s") % e)

        _logger.info("%d products are successfully updated." % update_products_no)

        if kwargs.get('fetch_o_product'):
            """Return the Product ID"""
            return sp_product_list

    def update_sync_history(self, vals):
        from datetime import datetime
        SycnHis = self.env['marketplace.sync.history'].sudo()
        synhistory = SycnHis.search(
            [('marketplace_type', '=', 'shopify')], limit=1)
        if not synhistory:
            synhistory = SycnHis.search(
                [('marketplace_type', '=', 0)], limit=1)
            synhistory.write({'marketplace_type': 'shopify'})
        vals['last_product_sync'] = datetime.now()
        synhistory.write(vals)

    def shopify_fetch_products_from_odoo(self):
        url = '/rest/V1/products'
        type = 'POST'
        headers = {
            'Content-Type': 'application/json'
        }
        product_data = self.get_product_data()

        if not product_data:
            return
        updated_list = {}
        for product in product_data[0]:
            try:
                product_list,next_link = self.env[
                    'marketplace.connector'].shopify_api_call(
                    headers=headers,
                    url=url,
                    type=type,
                    data=product
                )
                if product_list.get('sku'):
                    updated_list[product_list['sku']] = product_list.get(
                        'id')
            except:
                pass
        if updated_list:
            for product in product_data[1]:
                if product.default_code in updated_list:
                    product.write({
                        'marketplace_type': 'shopify',
                        'shopify_id': str(
                            updated_list[product.default_code])
                    })
                    product.product_tmpl_id.write({
                        'marketplace_type': 'shopify',
                        'shopify_id': str(
                            updated_list[product.default_code])
                    })
        _logger.info("%s product(s) updated", len(updated_list))
        return {
            'type': 'ir.actions.client',
            'tag': 'reload'
        }

    def shopify_image_processing(self, image_url):
        if image_url:
            image = False
            # shopify_host = self.env['ir.config_parameter'].sudo().get_param('odoo11_shopify2.shopify_host')
            # image_url = 'http://' + shopify_host + '/pub/media/catalog/product' + file
            if requests.get(image_url).status_code == 200:
                image = base64.b64encode(
                    requests.get(image_url).content)
            return image
        else:
            return False

    def get_comb_indices(self, options):
        comb_indices = ''
        i = 1
        for value in [option.get('values') for option in options]:
            for cmb in value:
                if cmb not in comb_indices:
                    comb_indices += ',' + cmb if i != 1 else cmb
            i = 0 if i == 1 else 0
        print(comb_indices)
        return comb_indices
        # prints
        # Default Title,Red,Blue


    def create_feed_parent_product(self, product, instance_id):
        try:
            domain = [('parent', '=', True)]
            domain += [('shopify_id', '=', product['id'])]
            fp_product = self.env['shopify.feed.products'].sudo().search(domain, limit=1)
            if not fp_product:
                record = self.env['shopify.feed.products'].sudo().create({
                    'instance_id': self.instance_id.id if self.instance_id else instance_id.id,
                    'parent': True,
                    'title': product['title'],
                    'shopify_id': product['id'],
                    'inventory_id': product.get('inventory_item_id'),
                    'product_data': json.dumps(product),
                })
                record._cr.commit()
                _logger.info("Shopify Feed Parent Product Created-{}".format(record))
                return record
            else:
                fp_product.write({
                    'product_data': json.dumps(product),
                    'inventory_id': product.get('inventory_item_id')
                })
                return fp_product
        except Exception as e:
            _logger.warning("Exception-{}".format(e.args))
