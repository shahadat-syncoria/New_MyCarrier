# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

import logging
import json
import pprint
from odoo import models, fields, api, exceptions, _
_logger = logging.getLogger(__name__)
import requests
from odoo.addons.odoosync_base.utils.app_marketplace import AppMarketplace

class ShopifyConnect(models.Model):
    _inherit = 'marketplace.connector'

    def shopify_api_call(self, **kwargs):
        """
        We will be running the api calls from here
        :param kwargs: dictionary with all the necessary parameters,
        such as url, header, data,request type, etc
        :return: response obtained for the api call
        """
        if kwargs.get('kwargs'):
            kwargs = kwargs.get('kwargs')
        if not kwargs:
            # no arguments passed
            return

        req_type = kwargs.get('type') or 'GET'
        complete_url = kwargs.get('url')
        headers = kwargs.get('headers')

        """
        {
            "service_name":"shopify",
            "data":{
                "type": "GET",
                "shopify_endpoint": "/admin/oauth/access_scopes.json",
                "payload":{},
                "params":{
                    "limit":250
                }
            }
        }
        """
        
        payload = {
            "type": req_type,
            "shopify_endpoint": complete_url,
            "payload": kwargs.get('data', {}),
            "params": kwargs.get('params', {}),
            "is_raw_endpoint":kwargs.get('is_raw_endpoint', False),
        }
        try:
            # if req_type not in ['GET','get']:
            #     raise exceptions.UserError(_("Pushing to shopify not allowed!"))
            app = AppMarketplace(service_name='shopify', service_key=headers.get('X-Service-Key'))
            app.data = payload
            res = app.marketplace_process(company_id=kwargs.get('marketplace_instance_id').company_id.id, env=self.env)
            next_link = res['links'] if res.get('links') else None
            if res.get('errors'):
                _logger.warning(_("Error:" + str(res.get('errors'))))
            return res, next_link
        except Exception as e:
            _logger.info("Exception occured %s", e)
            raise exceptions.UserError(_("Error Occured 5 %s") % e)
