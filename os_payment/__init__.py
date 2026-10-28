# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

from odoo.addons.os_payment import models
from odoo.addons.os_payment import payment_apps
from odoo.addons.payment import setup_provider, reset_payment_provider


def pre_init_check(cr):
    from odoo.service import common
    from odoo.exceptions import ValidationError
    version_info = common.exp_version()
    server_serie = version_info.get('server_serie')
    if server_serie != '17.0':raise ValidationError('Module support Odoo series 17.0 found {}.'.format(server_serie))
    return True



# def post_init_hook(cr, registry):
#     pass
    # setup_provider(cr, registry, 'clik2pay')
    # setup_provider(cr, registry, 'rotessa')
    # setup_provider(cr, registry, 'globalpay')
# def post_init_hook(env):
#     setup_provider(env, 'clik2pay')
#     setup_provider(env, 'rotessa')
#     # setup_provider(env, 'globalpay')
#
#
# def uninstall_hook(env):
#     reset_payment_provider(env, 'clik2pay')
#     reset_payment_provider(env, 'rotessa')
#     # reset_payment_provider(env, 'globalpay')
