# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, exceptions
from odoo.http import request
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


def error_response(msg: str = '', status_code: int = 501, route_type='json'):
    res = {
        "status_code": status_code,
        "error": {
            "message": msg,
        }
    }
    if route_type == 'json':
        return res
    return http.Response(
        json.dumps(res),
        status=status_code,
        mimetype='application/json'
    )


def response(data, status_code=200, route_type='json'):
    res = {
        "status_code": status_code,
        "result": data
    }
    if route_type == 'json':
        return res
    elif route_type == 'http':
        return http.Response(
            json.dumps(res),
            status=status_code,
            mimetype='application/json'
        )


class PosMonerisTerminalAPI(http.Controller):
    @http.route('/api/auth', type='json', auth="public")
    def authenticate(self, **post):
        values = json.loads(request.httprequest.data)
        try:
            print(values)
            login = values['params']["login"]
        except KeyError:
            raise exceptions.AccessDenied(message='`login` is required.')

        try:
            password = values['params']["password"]
        except KeyError:
            raise exceptions.AccessDenied(message='`password` is required.')

        db_name = http.request.db
        http.request.session.authenticate(db_name, login, password)
        session_info = request.env['ir.http'].session_info()
        api_key = request.env['res.users.apikeys']._generate('api', 'Auth key')
        res_user = request.env['res.users'].sudo().browse(session_info.get('uid'))
        token = None
        if res_user.company_id:
            omni_account = request.env['omni.account'].sudo().get_latest_omni_account_by_company(res_user.company_id)
            if omni_account:
                token = omni_account.token
        result = {
            "name": session_info['name'],
            "username": session_info['username'],
            "access_token": api_key,
            "connector_auth_token": token,
        }
        return response(result)

    @http.route('/api/payment/draft_go_payment', type='http', auth='api_key', methods=['GET'], csrf=False)
    def get_draft_go_payment(self, **params):
        moneris_payment_method = request.env['pos.payment.method'].sudo().get_moneris(params.get('terminal_id', False))
        if not moneris_payment_method:
            res = error_response('The Moneris payment method does not exist!', status_code=400, route_type='http')
            return res
        moneris_payments = request.env['pos.payment'].sudo().search([
            ('payment_method_id', 'in', moneris_payment_method.ids),
            ('payment_status', 'in', ['waiting']),
        ])

        data = [moneris_payment.get_draft_go_payment_data() for moneris_payment in moneris_payments]
        res = {
            "count": len(moneris_payments),
            "data": data
        }
        return response(res, route_type='http')

    @http.route('/api/payment/update', type='json', auth='api_key', methods=["POST"], csrf=False)
    def update_pos_payment(self, **post):
        try:
            post = json.loads(request.httprequest.data)['params']
        except KeyError:
            raise KeyError('`params` is required.')
        try:
            payment_transaction_id = post["payment_transaction_id"]
        except KeyError:
            raise KeyError('`payment_transaction_id` is required.')
        try:
            order_ref = post["order_ref"]
        except KeyError:
            raise KeyError('`order_ref` is required.')
        try:
            amount = post["amount"]
        except KeyError:
            raise KeyError(message='`amount` is required.')
        try:
            status = post["status"]
        except KeyError:
            raise KeyError(message='`status` is required.')

        pos_payment = request.env['pos.payment'].sudo().search([
            ('pos_payment_transaction', '=', payment_transaction_id),
            ('pos_order_id.pos_reference', '=', order_ref),
        ])

        if not pos_payment:
            res = error_response('The payment does not exist!', status_code=400)
            return res
        if pos_payment.payment_status == 'done':
            res = error_response('The payment has been done!', status_code=400)
            return res
        if (float_compare(amount, 0, precision_digits=2) <= 0 and float_compare(pos_payment.amount, 0,
                                                                                precision_digits=2) > 0):
            res = error_response('The amount must be greater than 0!', status_code=400)
            return res

        try:
            pos_payment.sudo().handle_moneris_payment_response(post)
        except KeyError as e:
            raise e
        return response({
            "message": "Update payment successfully."
        })

    @http.route('/api/device', type='http', auth='api_key', methods=['GET'], csrf=False)
    def get_moneris_device(self, **params):
        try:
            moneris_device_id = int(params["id"])
            uuid = params["uuid"]
        except KeyError:
            raise KeyError('`id` is required.')
        moneris_device = request.env['moneris.device'].sudo().browse(moneris_device_id)
        if not moneris_device:
            return error_response('The Moneris device does not exist!', status_code=400, route_type='http')
        moneris_device.sudo().write({
            "code": uuid
        })
        result = {
            "name": moneris_device.name,
            "code": moneris_device.code
        }
        return response(result, route_type='http')
