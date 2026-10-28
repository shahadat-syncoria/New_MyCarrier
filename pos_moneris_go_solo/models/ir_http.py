from odoo import models
from odoo.http import request, BadRequest
from odoo.exceptions import MissingError, AccessDenied


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_api_key(cls):
        api_key = request.httprequest.headers.get("Authorization")
        if not api_key:
            raise MissingError("'Authorization' header with API key missing!")

        user_id = request.env["res.users.apikeys"].sudo()._validate_api_key(
            scope="api", key=api_key
        )
        if not user_id:
            raise AccessDenied("API key invalid")

        request.update_env(user_id)
