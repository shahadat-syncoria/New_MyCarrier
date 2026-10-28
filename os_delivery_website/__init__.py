# -*- coding: utf-8 -*-
from odoo.addons.os_delivery_website import controllers
from odoo.addons.os_delivery_website import delivery_apps
from odoo import api, SUPERUSER_ID


def uninstall_hook(env):
    delivery_apps = env['delivery.carrier'].search([('delivery_type', 'in', ['purolator','canadapost'])])
    for delivery in delivery_apps:
        delivery.write({
            'is_published': False
        })