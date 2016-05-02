# -*- encoding: utf-8 -*-
##############################################################################
#
#    Product Variant CSV Import module for Odoo
#    Copyright (C) 2014 Akretion (http://www.akretion.com)
#    @author Alexis de Lattre <alexis.delattre@akretion.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp import api, fields, models, _
from openerp.addons.base.ir.ir_fields import ImportWarning


class ProductProduct(models.Model):
    _inherit = 'product.product'

    attribute_value_ids = fields.Many2many(
        readonly=False,
        create_on_import=True,
    )
    # In the "product" module, attribute_value_ids is Readonly=True
    # but this blocks the import of products template with variants via CSV


DELETE_ME_NAME = u"DOOMED!!!"
DOOMED = [("name", "=", DELETE_ME_NAME)]

# values taken from openerp.addons.base.ir.ir_fields
_CREATE = 0
_UPDATE = 1


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def load(self, fields, data):
        """Manage savepoint since we'll be creating objects before the
        BaseModel savepoint in its `load()`"""
        try:
            self.env.cr.execute('SAVEPOINT comodel_load_save')
            result = super(ProductTemplate, self).load(fields, data)
        except:
            self.env.cr.execute('ROLLBACK TO SAVEPOINT comodel_load_save')
            raise
        else:
            if result['ids'] in (False,):
                # there was an error in the messages
                self.env.cr.execute('ROLLBACK TO SAVEPOINT comodel_load_save')
            else:
                doomed = self.search(DOOMED)
                doomed.unlink()
                self.env.cr.execute('RELEASE SAVEPOINT comodel_load_save')
        return result

    @api.multi
    def _write(self, vals):
        # Avoid duplicating lines by changing CREATE commands for lines
        # matching the subfield value of existing lines into update commands.
        for field, subfield in [('attribute_line_ids', 'attribute_id'),
                                ('product_variant_ids', 'default_code')]:
            line_changes = vals.get(field)
            if not line_changes:
                continue

            def get_line_key(line, subfield):
                value = line[subfield]
                return (
                    value.id
                    if subfield.endswith("_id")
                    else value
                )
            # create map of subfield values to lines
            line_map = {
                get_line_key(line, subfield): line for line in self[field]
            }
            # check if there's already a line with the subfield value to be
            # created
            for i, (_command, _id, _writable) in enumerate(line_changes):
                if ((_command, _id) == (_CREATE, False) and
                        _writable.get(subfield) in line_map):
                    # update it instead of creating a new one
                    line = line_map[_writable[subfield]]
                    line_changes[i] = (_UPDATE, line.id, _writable)

        result = super(ProductTemplate, self)._write(vals)
        return result


class IrFieldsConverter(models.Model):

    _inherit = 'ir.fields.converter'

    @api.model
    def db_id_for(self, model, field, subfield, value):
        try:
            return super(IrFieldsConverter, self).db_id_for(
                model, field, subfield, value
            )
        except ValueError as e:
            # NOTE: We need a better exception than ValueError
            if not e.args[0].startswith(u"No matching record found for"):
                # XXX: Translation could trip us up above, but the worst that
                # can happen is an import failure, which will be rolled back
                raise
            model_field = (
                "%s.%s" % (field.model_name, field.name)
            )
            if model_field != 'product.template.product_variant_ids':
                raise
            if subfield not in (None, 'id'):
                raise

            warnings = [ImportWarning(e.args[0])]
            xml_id, field_type = {
                'id': (value, _(u"external id")),
                None: (None, _(u"name")),
            }[subfield]

            ModelData = self.env['ir.model.data']
            id = ModelData._update(
                model=field.comodel_name,
                module='',
                # the name here will be overwritten by product.template but
                # is required:
                values={'name': DELETE_ME_NAME},
                xml_id=value if subfield == 'id' else None,
            )
            return id, field_type, warnings
