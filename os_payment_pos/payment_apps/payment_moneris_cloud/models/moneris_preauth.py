import logging

from odoo import fields, models, api
from odoo.addons.odoosync_base.utils.app_payment import AppPayment
import random
import string
import json
import time
from datetime import datetime
_logger = logging.getLogger(__name__)


class MonerisPreauth(models.Model):
    _name = "moneris.pos.preauth"
    _inherit = ["portal.mixin", "pos.bus.mixin", "pos.load.mixin", "mail.thread"]
    _description = "Point of Sale Preauth"
    _order = "order_date desc, name desc, id desc"

    name = fields.Char('Preauth Name')
    order_date = fields.Datetime('Order Date')
    order_id = fields.Char(string="Order ID")
    terminal_id = fields.Char(string="Terminal ID")
    total_amount = fields.Float(string="Total Amount")
    settled_amount = fields.Float(string="Settled Amount", default=0.0)
    transaction_id = fields.Char(string="Transaction ID")
    status = fields.Selection([('pending', 'Pending'),
                               ('confirmed', 'Confirmed'),
                               ('failed', 'Failed'),('voided', 'Voided'),
                               ('settled','Settled')])
    customer_id = fields.Many2one('res.partner', string="Customer")
    moneris_go_payment_method = fields.Many2one('pos.payment.method', string="Payment Method")
    moneris_settled_order_id = fields.Many2one('pos.order', string="Settled Order")

    @staticmethod
    def generate_idempotency_key():
        current_time_struct = time.localtime()
        timestamp_part = time.strftime("%Y%m%d%H%M%S", current_time_struct)
        random_part = random.randint(10, 99)
        idempotency_key = f"{timestamp_part}{random_part}"
        return idempotency_key

    @api.model
    def moneris_preauth_req(self, customer_id, amount,payment_method, *extra):
        # use sudo() if POS user may lack access on res.partner
        partner = self.env["res.partner"].sudo().browse(int(customer_id))
        # _logger.info("Moneris preauth request: partner_id=%s name=%s amount=%s",
        #              customer_id, partner.name, amount)
        payment_method = self.env['pos.payment.method'].sudo().browse(payment_method)

        rand_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Combine customer_id with random part
        order_id = f"{customer_id}{rand_suffix}"

        srm = AppPayment(service_name="moneris_cloud_go", service_type="pre_authorization", service_key=payment_method.token)
        srm.data = {
            "order_id": order_id,
            "amount": amount,
            "terminal_id": payment_method.cloud_terminal_id,
            "idempotency_key": self.generate_idempotency_key()
        }

        # do your logic here …
        response = srm.payment_process(company_id=payment_method.company_id.id)
        # _logger.info(response)


        if response.get("errors"):
            if 'data' in response.get("errors"):
                error_desc = "An error has occurred. Please try again later."
                try:
                    data = response.get('errors').get('data')['response'][0]
                    error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                except :
                    pass
                response = {"error":True,"description":error_desc}
            else:
                response = {"error":True,"description":response.get("errors")}

        elif response.get("error"):
            response = {"error":True,"description":response.get("error")}
        elif response.get("errors_message",False):
            response = {"error": True, "description": response.get("errors_message")}
        else:
            if response["receipt"]["statusCode"] in ["5207"]:
                res_data = response["receipt"]["data"]['response'][0]
                self.create({
                    "name": f"Preauth - {res_data['orderId']}",
                    "order_id": res_data['orderId'],
                    "customer_id":partner.id,
                    "order_date": datetime.strptime(res_data.get("dataTimestamp"), "%Y-%m-%d %H:%M:%S")
                    if res_data.get("dataTimestamp") else fields.Datetime.now(),
                    "terminal_id": res_data.get("terminalId"),
                    "total_amount": float(res_data.get("approvedAmount", 0)) / 100.0,
                    "settled_amount": 0.0,
                    "transaction_id": res_data.get("transactionId"),
                    "status": "confirmed" if res_data.get("status") == "Approved" else "failed",
                    "moneris_go_payment_method": payment_method.id
                })

                response= {
                    "success": True,
                    "partner_id": partner.id,
                    "partner_name": partner.name or "",
                    "amount": float(amount),
                }
            else:
                if 'data' in response.get('receipt'):
                    error_desc = "An error has occurred. Please try again later."
                    try:
                        data = response.get('receipt').get('data')['response'][0]
                        error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                    except:
                        pass
                    response = {"error": True, "description": error_desc}
                else:
                    _logger.warning(response.get('receipt'))
                    response = {"error": True, "description": "Unknown Error"}


        return json.dumps(response)

        # IMPORTANT: return something JSON-serializable
        # return {
        #     "ok": True,
        #     "partner_id": partner.id,
        #     "partner_name": partner.name or "",
        #     "amount": float(amount),
        # }

    @api.model
    def moneris_preauth_void_req(self, order, *extra):
        # use sudo() if POS user may lack access on res.partner
        # _logger.info("Moneris preauth request: partner_id=%s name=%s amount=%s",
        #              customer_id, partner.name, amount)
        payment_method = self.env['pos.payment.method'].sudo().browse(order['moneris_go_payment_method'][0])
        if not payment_method:
            response = {"error": True, "description": 'Associated moeneris GO payment method not found!'}
            return json.dumps(response)
        moneris_preauth_id = self.sudo().browse(order["id"]).exists()
        if not moneris_preauth_id:
            response = {"error": True, "description": "Preauth record not found."}
            return json.dumps(response)
        if moneris_preauth_id.status != 'confirmed':
            response = {"error": True, "description": "Only confirmed preauthorizations can be voided."}
            return json.dumps(response)

        # Combine customer_id with random part

        srm = AppPayment(service_name="moneris_cloud_go", service_type="pre_authorization_void",
                         service_key=payment_method.token)
        srm.data = {
            "order_id": order["order_id"],
            "amount": float(moneris_preauth_id.total_amount),
            "transactionId": order["transaction_id"],
            # "terminal_id": payment_method["cloud_terminal_id"],
            "terminal_id": payment_method.cloud_terminal_id,
            "idempotency_key": self.generate_idempotency_key()
        }

        # do your logic here …
        response = srm.payment_process(company_id=payment_method.company_id.id)
        # _logger.info(response)

        if response.get("errors"):
            if 'data' in response.get("errors"):
                error_desc = "An error has occurred. Please try again later."
                try:
                    data = response.get('errors').get('data')['response'][0]
                    error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                except :
                    pass
                response = {"error":True,"description":error_desc}
            else:
                response = {"error":True,"description":response.get("errors")}

        elif response.get("error"):
            response = {"error": True, "description": response.get("error")}
        elif response.get("errors_message", False):
            response = {"error": True, "description": response.get("errors_message")}
        else:
            if response["receipt"]["statusCode"] in ["5207"]:
                res_data = response["receipt"]["data"]['response'][0]
                moneris_preauth_id.write({
                    'status': 'voided',
                })

                response = {
                    "success": True,

                }
            else:
                if 'data' in response.get('receipt'):
                    error_desc = "An error has occurred. Please try again later."
                    try:
                        data = response.get('receipt').get('data')['response'][0]
                        error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                    except:
                        pass
                    response = {"error": True, "description": error_desc}
                else:
                    _logger.warning(response.get('receipt'))
                    response = {"error": True, "description": "Unknown Error"}

        return json.dumps(response)

    @api.model
    def moneris_preauth_complete_req(self, order, payment_method, pos_order, amount=None, *extra):
        # use sudo() if POS user may lack access on res.partner
        # _logger.info("Moneris preauth request: partner_id=%s name=%s amount=%s",
        #              customer_id, partner.name, amount)
        payment_method = self.env['pos.payment.method'].sudo().browse(payment_method)
        if not payment_method:
            response = {"error": True, "description": 'Associated moeneris GO payment method not found!'}
            return json.dumps(response)

        moneris_preauth_id = self.sudo().browse(order["id"]).exists()
        if not moneris_preauth_id:
            response = {"error": True, "description": "Preauth record not found."}
            return json.dumps(response)
        if moneris_preauth_id.status != 'confirmed':
            response = {"error": True, "description": "This preauthorization has already been completed or voided."}
            return json.dumps(response)

        settle_amount = float(amount) if amount is not None else float(moneris_preauth_id.total_amount)
        authorized_amount = float(moneris_preauth_id.total_amount)
        if settle_amount <= 0:
            response = {"error": True, "description": "Settlement amount must be greater than 0."}
            return json.dumps(response)
        if settle_amount >= 1500.0 and settle_amount >= (authorized_amount * 4):
            response = {
                "error": True,
                "description": (
                    "Completion amount triggers the Moneris warning threshold. "
                    "Use a smaller amount or create a larger preauthorization."
                ),
            }
            return json.dumps(response)

        # Combine customer_id with random part

        srm = AppPayment(service_name="moneris_cloud_go", service_type="pre_authorization_complete",
                         service_key=payment_method.token)
        srm.data = {
            "order_id": order["order_id"],
            "amount": settle_amount,
            "transactionId": order["transaction_id"],
            # "terminal_id": payment_method["cloud_terminal_id"],
            "terminal_id": payment_method.cloud_terminal_id,
            "idempotency_key": self.generate_idempotency_key()
        }

        # do your logic here …
        response = srm.payment_process(company_id=payment_method.company_id.id)
        # _logger.info(response)
        if response.get("errors"):
            if 'data' in response.get("errors"):
                error_desc = "An error has occurred. Please try again later."
                try:
                    data = response.get('errors').get('data')['response'][0]
                    error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                except:
                    pass
                response = {"error": True, "description": error_desc}
            else:
                response = {"error": True, "description": response.get("errors")}
        elif response.get("error"):
            response = {"error": True, "description": response.get("error")}
        elif response.get("errors_message", False):
            response = {"error": True, "description": response.get("errors_message")}
        else:
            if response["receipt"]["statusCode"] in ["5207"]:
                moneris_preauth_id.write({
                    'settled_amount': settle_amount,
                    'status': 'settled',
                    'moneris_settled_order_id': pos_order,
                })

                response = {
                    "success": True,
                    "amount": settle_amount,
                    "settled_amount": settle_amount,
                }
            else:
                if 'data' in response.get('receipt'):
                    error_desc = "An error has occurred. Please try again later."
                    try:
                        data = response.get('receipt').get('data')['response'][0]
                        error_desc = f"{data.get('status')}\nError Code: {data.get('statusCode')}"
                    except:
                        pass
                    response = {"error": True, "description": error_desc}
                else:
                    _logger.warning(response.get('receipt'))
                    response = {"error": True, "description": "Unknown Error"}

        return json.dumps(response)
