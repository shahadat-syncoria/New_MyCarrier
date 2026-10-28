/** @odoo-module **/
import {Component, useRef, useState} from "@odoo/owl";
import {usePos} from "@point_of_sale/app/store/pos_hook";
import {useService} from "@web/core/utils/hooks";
import {ControlButtons} from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import {patch} from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import {MonerisGoPreauthPopup} from "../popup/preauth_popup";



patch(ControlButtons.prototype, {

      async onClickPreauthView(event) {
        this.dialog.add(MonerisGoPreauthPopup, {
            title: 'Moneris Go Preauth List',
            cancel: () => true,
        });
    }
});