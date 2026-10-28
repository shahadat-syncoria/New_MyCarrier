import time

from odoo import models
from odoo.addons.base.models.res_users import INDEX_SIZE, KEY_CRYPT_CONTEXT

from odoo.addons.pos_moneris_go_solo.exceptions.ExpireAPIKey import ExpireAPIKey


class APIKeys(models.Model):
    _inherit = 'res.users.apikeys'

    def _validate_api_key(self, *, scope, key):
        assert scope, "scope is required"
        index = key[:INDEX_SIZE]
        self.env.cr.execute('''
            SELECT u_api.id as id, u_api.key as key
            FROM {} u_api INNER JOIN res_users u ON (u.id = u_api.user_id)
            WHERE u.active and u_api.index = %s AND (u_api.scope IS NULL OR u_api.scope = %s)
        '''.format(self._table),
                            [index, scope])
        for info in self.env.cr.dictfetchall():
            if KEY_CRYPT_CONTEXT.verify(key, info['key']):
                res_user_apikey = self.browse(info['id'])
                expire_token_time = int(self.env['ir.config_parameter'].sudo().get_param('syncoria.expire.token.time',
                                                                                         default=60))
                if time.time() - res_user_apikey.create_date.timestamp() > expire_token_time * 60:
                    raise ExpireAPIKey('The API key was expired!')
                return res_user_apikey.user_id
        return None
