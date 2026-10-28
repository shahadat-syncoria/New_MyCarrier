# -*- coding: utf-8 -*-

{
    'name': 'POS Moneris go - Solo',
    'summary': 'Syncoria POS Moneris Terminal - Solo',
    'description': """
        Payment method on POS with Moneris Go terminal - Solo
    """,
    'category': 'pos',
    
    "author": "Syncoria Inc.",
    "website": "https://www.syncoria.com",
    "company": "Syncoria Inc.",
    "maintainer": "Syncoria Inc.",
    "license": "OPL-1",
    "support": "support@syncoria.com",
    "price": 5000,
    "currency": "USD",
    'depends': [
        'odoosync_base', 'point_of_sale', 'account_payment','payment',
    ],
    'sequence': 4,

    'data': [
        # data
        'security/ir.model.access.csv',
        'data/ir_config_parameters.xml',
        'data/pos_payment_methods.xml',
        # views
        'views/pos_payment_method_views.xml',
        'views/inherited_pos_payment_inherit_syncoria_pos_terminal.xml',
        'wizards/pos_refund_wizard_form.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_moneris_go_solo/static/src/js/**/*',
            'pos_moneris_go_solo/static/src/xml/**/*',
            'pos_moneris_go_solo/static/src/scss/**/*',
        ]
    },
    'qweb': [

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
