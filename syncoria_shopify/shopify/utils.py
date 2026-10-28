# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################
import pprint
import re
import json
from sys import api_version
import requests
from odoo import models, api, fields, tools, exceptions, _
from odoo import exceptions
import logging

_logger = logging.getLogger(__name__)


def get_provar_vals(record, values):
    data = {}
    product = {
        'id': record.shopify_id,
        # 'product_id': 6929081696441,
        'title': record.name,
        'price': record.list_price,
        'sku': record.default_code,
        # 'position': 1,
        # 'inventory_policy': 'deny',
        'compare_at_price': record.shopify_compare_price,
        # 'fulfillment_service': 'manual',
        # 'inventory_management': None,
        # 'option1': 'Default Title',
        # 'option2': None,
        # 'option3': None,
        'taxable': record.shopify_charge_tax,
        'status': record.shopify_product_status,
        'barcode': record.barcode,
        # 'grams': 0,
        # 'image_id': None,
        'weight': record.weight,
        'weight_unit': record.uom_id.name,
        # 'inventory_item_id': 42940912238777,
        'inventory_quantity': record.qty_available,
        # 'old_inventory_quantity': 0,
        'requires_shipping': True if record.type == 'product' else False
    }
    if record.qty_available:
        product['inventory_quantity'] = int(record.qty_available)

    product = {k: v for k, v in product.items() if v}
    data["product"] = product
    return data


def get_protmpl_vals(record, action, mapping, instance, images=False):
    data = {}
    product = {}

    if 'product.template' in str(record):
        product.update({
            "title": record.name,
            "body_html": record.description_sale or '',
            "vendor": record.shopify_vendor or "",
            "product_type": record.categ_id.name or "",
            "status": record.shopify_product_status,
            "tags": record.shopify_tags or '',
        })
        if action == 'update':
            product.update({'id': mapping.shopify_parent_id})
        variants = []
        variants_rec = record.product_variant_ids
        instance_id = instance
        if instance_id.compute_pricelist_price:
            record.compute_shopify_price(instance_id)
        for var in variants_rec:
            variant_mapping = record.env['shopify.product.mappings'].search([('product_id', '=', var.id),('shopify_instance_id', '=', instance.id)], limit=1)
            exclude_variant = False
            for attrib in var.product_template_attribute_value_ids:
                if attrib.product_attribute_value_id in record.attribute_line_ids.shopify_value_ids:
                    _logger.info("EXCLUDE VARIANT")
                    _logger.info(attrib.product_attribute_value_id.display_name)
                    exclude_variant = True or exclude_variant
            if exclude_variant:
                continue
            variant = {}
            var.compute_shopify_price(instance_id)
            shopify_price = var.shopify_price or var.lst_price
            count = 1
            _logger.info("Variant Name ===>>>{}".format(var.name))
            _logger.info("Variant Price ===>>>{}".format(shopify_price))

            if var.product_template_attribute_value_ids:
                for attrib in var.product_template_attribute_value_ids:
                    _logger.info(attrib.attribute_id.name)
                    _logger.info(attrib.name)

                    variant["option" + str(count)] = attrib.name
                    count += 1
                    variant.update({
                        'title': var.name,
                        'price': shopify_price,
                        'sku': var.default_code or '',
                        'inventory_management': 'shopify',
                        'barcode': var.barcode or '',
                        'weight': var.weight,
                        'weight_unit': var.weight_uom_name,
                        'compare_at_price': var.product_tmpl_id.shopify_compare_price
                    })
                    if action == 'update' and variant_mapping:
                        variant.update({'id': variant_mapping.shopify_id})
                    variant = {k: v for k, v in variant.items()}
            else:
                variant = {
                    'title': var.name,
                    'price': shopify_price,
                    'sku': var.default_code or '',
                    'barcode': var.barcode or '',
                    'weight': var.weight,
                    'weight_unit': var.weight_uom_name,
                    'inventory_management': 'shopify',
                    'compare_at_price': var.product_tmpl_id.shopify_compare_price
                }
                if action == 'update':
                    variant.update({'id': variant_mapping.shopify_id})
            if len(variant) > 0:
                variants.append(variant)

        product["variants"] = variants
        options = []
        for att_line in record.attribute_line_ids.filtered(lambda att_line: att_line.attribute_id.create_variant != 'no_variant'):
            option = {"name": att_line.attribute_id.name, "values": []}
            for value_id in att_line.value_ids:
                if value_id.id not in att_line.shopify_value_ids.ids:
                    option["values"].append(value_id.name)
            options.append(option)
        if options:
            product["options"] = options
        product['images'] = []
        """ LEGACY """
        # try:
        #     product['images'] = []
        #     if record.image_1920 and instance_id.set_image:
        #         product.update({
        #             "images": [{
        #                 "attachment": record.image_1920.decode(),
        #             }]
        #         })
        #         product_image = image_data_uri(record.image_1920)
        #     for image in record.product_template_image_ids:
        #         product['images'] += [{
        #             "attachment": image.image_1920.decode()
        #         }]
        # except Exception as e:
        #     _logger.info("Exception In Decoding Images-%s", e.args)

        # if instance_id.set_image and images:
        #     try:
        #         product['images'] = []
        #         product.update({
        #             "images": [{"src": image} for image in images]
        #         })
        #     except Exception as e:
        #         _logger.info("Exception In Decoding Images-%s", e.args)

        product = {k: v for k, v in product.items()}
        data["product"] = product
        _logger.info("\nDATA===>>>\n" + pprint.pformat(data))
    elif 'product.product' in str(record):
        mapping_tmpl = record.env['shopify.product.mappings'].search([('product_tmpl_id', '=', record.product_tmpl_id.id), ('shopify_instance_id', '=', instance.id)], limit=1)
        variant = {"product_id": mapping_tmpl.shopify_parent_id, "sku": record.default_code or '',
                   'weight': record.weight,
                   'weight_unit': record.weight_uom_name,
                   "barcode": record.barcode or ''}
        if action == 'update':
            del variant['product_id']
            variant['id'] = mapping.shopify_id
        if mapping.shopify_instance_id.compute_pricelist_price:
            record.compute_shopify_price(mapping.shopify_instance_id)
        if mapping.shopify_instance_id.set_price:
            variant["price"] = record.shopify_price or record.lst_price
        position = 1
        for att in record.product_template_variant_value_ids.sorted():
            value = record.env['product.attribute.value'].browse(att.product_attribute_value_id.id)
            variant['option' + str(position)] = value.name
            position += 1
        data['variant'] = variant
        _logger.info("\nDATA===>>>\n" + pprint.pformat(data))
    return data

# def get_marketplace(record):
#     """This function return the marketplace
#
#     Args:
#         record (`product.product`): Variant Object
#     """
#     ICPSudo = record.env['ir.config_parameter'].sudo()
#     try:
#         marketplace_instance_id = ICPSudo.get_param(
#             'syncoria_base_marketplace.marketplace_instance_id')
#         marketplace_instance_id = [int(s) for s in re.findall(
#             r'\b\d+\b', marketplace_instance_id)]
#     except:
#         marketplace_instance_id = False
#     if marketplace_instance_id:
#         marketplace_instance_id = record.env['marketplace.instance'].sudo().search(
#             [('id', '=', marketplace_instance_id[0])])
#     return marketplace_instance_id


# def update_product_images(record, product_data, req_type):
#     """_summary_
#
#     Args:
#         record (_type_): _description_
#         product_data (_type_): _description_
#         req_type (_type_): _description_
#     """
#     _logger.info("[START]-Upload Product Images.....")
#     import datetime
#     start_time = datetime.datetime.now()
#     time_lag = 0.5  # 0.5seconds
#     _logger.info("start_time-{}".format(start_time))
#
#     data = {}
#     attachments = [record.image_1920.decode()] if record.image_1920 else []
#     if not record.shopify_image_id:
#         req_type = 'create'
#
#     for attachment in attachments:
#         _logger.info("attachment-{}".format(attachment))
#         while True:
#             current_time = datetime.datetime.now()
#             if (current_time - start_time).seconds > time_lag:
#                 start_time = datetime.datetime.now()
#                 data = {
#                     "image":
#                         {
#                             "variant_ids": [record.shopify_id],
#                             "attachment": attachment
#                         }
#                 }
#                 marketplace_instance_id = record.shopify_instance_id or get_marketplace(record)
#                 version = marketplace_instance_id.marketplace_api_version or '2021-01'
#                 url = marketplace_instance_id.marketplace_host
#                 if req_type == 'create':
#                     type_req = 'POST'
#                     url += '/admin/api/%s/products/%s/images.json' % (
#                         version, product_data.shopify_id)
#                 if req_type == 'update':
#                     type_req = 'PUT'
#                     url += '/admin/api/%s/products/%s/images/%s.json' % (
#                         version, product_data.shopify_id, record.shopify_image_id)
#                 headers = {
#                     'X-Service-Key': marketplace_instance_id.token,
#                     'Content-Type': 'application/json'
#                 }
#                 updated_products, next_link = shopify_api_call(
#                     headers=headers,
#                     url=url,
#                     type=type_req,
#                     marketplace_instance_id=marketplace_instance_id,
#                     data=data
#                 )
#                 if "errors" not in updated_products:
#                     var = record.write({
#                         "shopify_image_id": updated_products["image"]["id"]
#                     })
#
#                 break
#
#     _logger.info("[END]-Upload Product Images.....")

def update_image_shopify(marketplace_instance_id, image, product_id, variant_id=False):
    try:
        if marketplace_instance_id.set_image:
            mapping = product_id.env['shopify.product.mappings'].search([('product_tmpl_id', '=', product_id.id),('shopify_instance_id', '=', marketplace_instance_id.id)], limit=1)
            headers = {
                'X-Service-Key': marketplace_instance_id.token,
            }
            data = {"image": {"attachment": image.decode()}}
            if variant_id:
                variant_mapping = variant_id.env['shopify.product.mappings'].search([('product_id', '=', variant_id.id),('shopify_instance_id', '=', marketplace_instance_id.id)], limit=1)
                data["image"]["variant_ids"] = [int(variant_mapping.shopify_id)]
            created_images, next_link = product_id.env['marketplace.connector'].shopify_api_call(
                headers=headers,
                url='/products/%s/images.json' % mapping.shopify_parent_id,
                type='POST',
                marketplace_instance_id=marketplace_instance_id,
                data=data
            )
            _logger.info(created_images)
    except Exception as e:
        _logger.info(e)

        # if variant_images and variant_images.get(var_id.id):
        #     data = {"image": {"src": variant_images.get(var_id.id), "variant_ids": [int(var_id.shopify_id)]}}
        #     created_images, next_link = record.env['marketplace.connector'].shopify_api_call(
        #         headers=headers,
        #         url='/products/%s/images.json' % var_id.shopify_parent_id,
        #         type='POST',
        #         marketplace_instance_id=marketplace_instance_id,
        #         data=data
        #     )
        #     _logger.info(created_images)

def shopify_pt_request(record, data, req_type, mapping, instance, attachment_ids=False, variant_images=False):
    marketplace_instance_id = instance
    if 'product.template' in str(record):
        type_req = 'POST'
        url = '/products.json'
        if req_type == 'update':
            type_req = 'PUT'
            url = '/products/%s.json' % mapping.shopify_parent_id
    elif 'product.product' in str(record):
        type_req = 'POST'
        url = '/products/%s/variants.json' % mapping.shopify_parent_id
        if req_type == 'update':
            type_req = 'PUT'
            url = '/variants/%s.json' % mapping.shopify_id

    headers = {
        'X-Service-Key': marketplace_instance_id.token,
    }
    created_products, next_link = record.env['marketplace.connector'].shopify_api_call(
        headers=headers,
        url=url,
        type=type_req,
        marketplace_instance_id=marketplace_instance_id,
        data=data
    )
    _logger.info("\ncreated_products--->\n" + pprint.pformat(created_products))

    if created_products.get('errors'):
        raise exceptions.UserError(_(created_products.get('errors')))
    elif created_products.get('product', {}).get("id"):
        # if not record.shopify_id:
        #     shopify_id = created_products.get("product", {}).get("id")
        #     product_vals = {
        #         'shopify_id': shopify_id,
        #         'marketplace_instance_id': marketplace_instance_id.id,
        #     }
        #     record.write(product_vals)
        if record.image_1920:
            update_image_shopify(marketplace_instance_id, record.image_1920, record)
        if 'product_template_image_ids' in record:
            for image in record.product_template_image_ids:
                update_image_shopify(marketplace_instance_id, image.image_1920, record)
        if created_products.get('product', {}).get("variants"):
            if len(created_products.get('product', {}).get("variants")) == 1:
                variant = created_products.get('product', {}).get("variants")[0]
                product_ids = record.env['product.product'].sudo().search(
                    [('product_tmpl_id', '=', record.id)])
                if len(product_ids) == 1:
                    val_dict = {
                        'name': variant.get('sku'),
                        'shopify_instance_id': marketplace_instance_id.id,
                        'product_id': product_ids.id,
                        'shopify_id': variant.get('id'),
                        'shopify_parent_id': variant.get('product_id'),
                        'shopify_inventory_id': variant.get('inventory_item_id')
                    }
                    if not mapping:
                        prod_mapping = record.env['shopify.product.mappings'].sudo().create(val_dict)
                else:
                    _logger.warning('There is something wrong')
            if len(created_products.get('product', {}).get("variants")) > 1:
                """Update Variants for the Products"""
                variants = created_products.get('product', {}).get("variants")
                options = created_products.get('product', {}).get("options")
                options_dict = {}
                for opt in options:
                    options_dict['option' + str(opt['position'])] = opt['name']
                for var in variants:
                    fields = list([key for key, value in var.items()])
                    pro_domain = []
                    ptav_ids = []
                    for key, value in options_dict.items():
                        if key in fields:
                            attribute_id = record.env['product.attribute'].sudo().search([('name', '=', value)],
                                                                                         limit=1).id
                            domain = [('attribute_id', '=', attribute_id)]
                            domain += [('name', '=', var[key]), ('product_tmpl_id', '=', record.id)]
                            ptav = record.env['product.template.attribute.value'].sudo().search(domain, limit=1)
                            ptav_ids += ptav.ids
                    pro_domain += [('product_tmpl_id', '=', record.id)]
                    if len(ptav_ids) > 1:
                        for ptav_id in ptav_ids:
                            pro_domain += [('product_template_attribute_value_ids', '=', ptav_id)]
                    elif len(ptav_ids) == 1:
                        pro_domain += [('product_template_attribute_value_ids', 'in', ptav_ids)]

                    var_id = record.env['product.product'].sudo().search(pro_domain, limit=1)
                    _logger.info("pro_domain-->%s", pro_domain)

                    if var_id:
                        val_dict = {
                            'name': var.get('sku'),
                            'shopify_instance_id': marketplace_instance_id.id,
                            'product_id': var_id.id,
                            'shopify_id': var.get('id'),
                            'shopify_parent_id': var.get('product_id'),
                            'shopify_inventory_id': var.get('inventory_item_id')
                        }
                        variant_mapping = record.env['shopify.product.mappings'].search([('product_id', '=', var_id.id),('shopify_instance_id', '=', marketplace_instance_id.id)], limit=1)
                        if not variant_mapping:
                            prod_mapping = record.env['shopify.product.mappings'].sudo().create(val_dict)
                        try:
                            var_id._cr.commit()
                            if var_id.image_1920:
                                update_image_shopify(marketplace_instance_id, var_id.image_1920, record, var_id)
                        except Exception as e:
                            _logger.info("Exception===>>>{}".format(e.args))
            # Update cost
            record.action_update_shopify_cost_product(marketplace_instance_id)

        body = _("Shopify Product " + req_type + " with Shopify ID: " + str(created_products.get("product").get("id")))
        _logger.info(body)
        record.message_post(body=body)

    elif created_products.get('variant', {}).get("id"):
        if not mapping:
            # shopify_id = created_products.get("variant", {}).get("id")
            # product_vals = {
            #     'shopify_id': shopify_id,
            #     'marketplace_instance_id': marketplace_instance_id.id,
            #     'shopify_inventory_id': created_products.get("variant", {}).get("inventory_item_id"),
            #     'shopify_parent_id': created_products.get("variant", {}).get("product_id")
            # }
            # record.write(product_vals)
            val_dict = {
                'name': created_products.get("variant", {}).get("sku"),
                'shopify_instance_id': marketplace_instance_id.id,
                'product_id': record.id,
                'shopify_id': created_products.get("variant", {}).get("id"),
                'shopify_parent_id': created_products.get("variant", {}).get("product_id"),
                'shopify_inventory_id': created_products.get("variant", {}).get("inventory_item_id")
            }
            prod_mapping = record.env['shopify.product.mappings'].sudo().create(val_dict)
            body = _(
                "Shopify Product Variant" + req_type + " with Shopify ID: " + str(
                    created_products.get("variant").get("id")))
            _logger.info(body)
            record.message_post(body=body)
        # Sync Image
        if marketplace_instance_id.set_image and record.image_1920:
            update_image_shopify(marketplace_instance_id, record.image_1920, record.product_tmpl_id, record)

        # Sync Cost
        record.action_update_shopify_cost_product(marketplace_instance_id)


# --------------------------------------------------------------------------------------------------------
# --------------------------------------Shopify Customer Functions----------------------------------------
# --------------------------------------------------------------------------------------------------------

def shopify_address_values(record):
    address = {}
    first_name = record.name.split(' ', 1)[1] if len(
        record.name.split(' ', 1)[1]) > 0 else ''
    last_name = record.name.split(' ', 1)[1] if len(
        record.name.split(' ', 1)) > 1 else ''

    address = {
        "address": {
            "address1": record.street or '',
            "address2": record.street2 or '',
            "city": record.city or '',
            "company": "Fancy Co.",
            "first_name": first_name,
            "last_name": first_name,
            "phone": record.phone,
            "province": record.state_id.name if record.state_id else '',
            "country": record.country_id.name if record.country_id else '',
            "zip": record.zip,
            "name": record.name,
            "province_code": record.state_id.code if record.state_id else '',
            "country_code": record.country_id.code if record.country_id else '',
            "country_name": record.country_id.name if record.country_id else '',
        }
    }

    address = {k: v for k, v in address.items() if v}

    return address


def shopify_customer_values(record):
    first_name = record.name.split(' ')[0] if len(
        record.name.split(' ', 1)) > 0 else ''
    last_name = record.name.split(' ', 1)[1] if len(
        record.name.split(' ', 1)) > 1 else ''
    customer = {
        "customer": {
            "first_name": first_name,
            "last_name": last_name,
            "email": record.email or '',
            "phone": record.phone or '',
            # Fields can be added
            'note': record.comment,
            'accepts_marketing': record.shopify_accepts_marketing,
            'currency': record.currency_id.name,
            # 'marketing_opt_in_level' : record.currency_id.name,
        }
    }

    customer = {k: v for k, v in customer.items() if v}
    customer["customer"]["default_address"] = shopify_address_values(record)
    pprint.pprint(customer)
    return customer


def shopify_cus_req(self, data, req_type):
    """This function call SHopify Api to get Customer Informations

    Args:
        data (dict): A dict of Customer Information
        req_type (['search','create','update']): Request Type

    Returns:
        dict: Dict containing customer response
    """
    marketplace_instance_id = get_marketplace(self)
    version = marketplace_instance_id.marketplace_api_version or '2021-01'
    url = marketplace_instance_id.marketplace_host
    if req_type == 'create':
        type_req = 'POST'
        url += '/admin/api/%s/customers.json' % version
    if req_type == 'update':
        type_req = 'PUT'
        url += '/admin/api/%s/customers/%s.json' % (version, self.shopify_id)
    if req_type == 'delete':
        type_req = 'DELETE'
        url += '/admin/api/%s/customers/%s.json' % (version, self.shopify_id)
    if req_type == 'search':
        type_req = 'GET'
        url += '/admin/api/%s/customers/search.json?query=email:%s&fields=email,id' % (
            version, self.email)

    headers = {
        'X-Service-Key': marketplace_instance_id.token,
        'Content-Type': 'application/json'
    }
    customer, next_link = self.env['marketplace.connector'].shopify_api_call(
        headers=headers,
        url=url,
        type=type_req,
        marketplace_instance_id=marketplace_instance_id,
        data=data
    )
    import json
    customer = json.dumps(customer)
    return customer


def shopify_add_req(self, data, req_type):
    """This function call Shopify Api to get Address Informations

    Args:
        data (dict): A dict of Address Information
        req_type (['search','create','update']): Request Type

    Returns:
        dict: Address Response
    """
    marketplace_instance_id = get_marketplace(self)
    version = marketplace_instance_id.marketplace_api_version or '2021-01'
    url = marketplace_instance_id.marketplace_host
    if req_type == 'create':
        type_req = 'POST'
        url += '/admin/api/%s/customers/%s/addresses.json' % (
            version, self.shopify_id)
    if req_type == 'update':
        type_req = 'PUT'
        url += '/admin/api/%s/customers/%s/addresses/%s.json' % (
            version, self.shopify_id, self.shopify_add_id)
    if req_type == 'delete':
        type_req = 'PUT'
        url += '/admin/api/%s/customers/%s/addresses/%s.json' % (
            version, self.shopify_id, self.shopify_add_id)

    if req_type == 'search':
        type_req = 'GET'
        url += '/admin/api/%s/customers/%s/addresses/%s.json' % (
            version, self.shopify_id, self.shopify_add_id)

    headers = {
        'X-Service-Key': marketplace_instance_id.token,
        'Content-Type': 'application/json'
    }
    address, next_link = self.env['marketplace.connector'].shopify_api_call(
        headers=headers,
        url=url,
        type=type_req,
        marketplace_instance_id=marketplace_instance_id,
        data=data
    )
    import json
    address = json.dumps(address)
    return address


def shopify_inventory_request(record, data, req_type):
    marketplace_instance_id = get_marketplace(record)
    version = marketplace_instance_id.marketplace_api_version or '2022-01'
    url = marketplace_instance_id.marketplace_host

    # "https://your-development-store.myshopify.com/admin/api/2022-01/inventory_items/808950810.json"

    if req_type == 'create' and 'product.template' in str(record):
        type_req = 'POST'
        url += '/admin/api/%s/inventory_items/%s.json' % (version, record.shopify_inventory_id)
    if req_type == 'update' and 'product.template' in str(record):
        type_req = 'PUT'
        url += '/admin/api/%s/inventory_items/%s.json' % (version, record.shopify_inventory_id)

    if req_type == 'create' and 'product.product' in str(record):
        type_req = 'POST'
        url += '/admin/api/%s/inventory_items/%s.json' % (version, record.shopify_inventory_id)
    if req_type == 'update' and 'product.product' in str(record):
        type_req = 'PUT'
        url += '/admin/api/%s/inventory_items/%s.json' % (version, record.shopify_inventory_id)

    headers = {
        'X-Service-Key': marketplace_instance_id.token,
        'Content-Type': 'application/json'
    }

    inventory_items, next_link = shopify_api_call(
        headers=headers,
        url=url,
        type=type_req,
        marketplace_instance_id=marketplace_instance_id,
        data=data
    )
    _logger.info("\inventory_items--->\n" + pprint.pformat(inventory_items))

    if inventory_items.get('errors'):
        # raise exceptions.UserError(_(inventory_items.get('errors')))
        body = "Variant Updated Error for Id-%s" % (inventory_items.get('errors'))
        record.message_post(body=body)
    elif inventory_items.get('inventory_item', {}).get("id"):
        body = "Variant Updated for Id-%s" % (inventory_items.get('inventory_item', {}).get("id"))
        record.message_post(body=body)
