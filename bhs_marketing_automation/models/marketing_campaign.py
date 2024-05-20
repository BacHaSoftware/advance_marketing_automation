# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import threading
from ast import literal_eval
from odoo import api, fields, models, tools, _
from odoo.fields import Datetime



class MarketingCampaign(models.Model):
    _inherit = 'marketing.campaign'

    model_id = fields.Many2one(
        'ir.model', string='Model', index=True, required=True, ondelete='cascade',
        default=lambda self: self.env['ir.model'].search([('model', '=', 'mailing.contact')], limit=1),
        domain="['&', ('is_mail_thread', '=', True), ('model', '!=', 'mail.blacklist')]")
    mass_mailing_ids = fields.Many2many('mailing.mailing', domain=[('mailing_type', '=', 'mail')],
                                        groups="mass_mailing.group_mass_mailing_user",
                                        compute="_compute_mass_mailing_ids")

    def sync_participants(self):
        """ Ghi đè hàm sync_participant """
        def _uniquify_list(seq):
            seen = set()
            return [x for x in seq if x not in seen and not seen.add(x)]

        participants = self.env['marketing.participant']
        # auto-commit except in testing mode
        auto_commit = not getattr(threading.current_thread(), 'testing', False)
        for campaign in self.filtered(lambda c: c.marketing_activity_ids):
            now = Datetime.now()
            if not campaign.last_sync_date:
                campaign.last_sync_date = now

            user_id = campaign.user_id or self.env.user
            RecordModel = self.env[campaign.model_name].with_context(lang=user_id.lang)

            # Fetch existing participants
            participants_data = participants.search_read([('campaign_id', '=', campaign.id)], ['res_id'])
            existing_rec_ids = _uniquify_list([live_participant['res_id'] for live_participant in participants_data])

            record_domain = literal_eval(campaign.domain or "[]")
            db_rec_ids = _uniquify_list(RecordModel.search(record_domain).ids)
            to_create = [rid for rid in db_rec_ids if rid not in existing_rec_ids]  # keep ordered IDs
            to_remove = set(existing_rec_ids) - set(db_rec_ids)
            unique_field = campaign.unique_field_id.sudo()
            if unique_field.name != 'id':
                without_duplicates = []
                existing_records = RecordModel.with_context(prefetch_fields=False).browse(existing_rec_ids).exists()
                # Split the read in batch of 1000 to avoid the prefetch
                # crawling the cache for the next 1000 records to fetch
                unique_field_vals = {rec[unique_field.name]
                                        for index in range(0, len(existing_records), 1000)
                                        for rec in existing_records[index:index+1000]}

                for rec in RecordModel.with_context(prefetch_fields=False).browse(to_create):
                    field_val = rec[unique_field.name]
                    # we exclude the empty recordset with the first condition
                    if (not unique_field.relation or field_val) and field_val not in unique_field_vals:
                        without_duplicates.append(rec.id)
                        unique_field_vals.add(field_val)
                to_create = without_duplicates

            BATCH_SIZE = 100
            for to_create_batch in tools.split_every(BATCH_SIZE, to_create, piece_maker=list):
                participants |= participants.create([{
                    'campaign_id': campaign.id,
                    'res_id': rec_id,
                } for rec_id in to_create_batch])

                # if auto_commit:
                #     self.env.cr.commit()

            if to_remove:
                participants_to_unlink = participants.search([
                    ('res_id', 'in', list(to_remove)),
                    ('campaign_id', '=', campaign.id),
                    ('state', '!=', 'unlinked'),
                ])
                for index in range(0, len(participants_to_unlink), 1000):
                    participants_to_unlink[index:index+1000].action_set_unlink()
                    # Commit only every 100 operation to avoid committing to often
                    # this mean every 10k record. It should be ok, it takes 1sec second to process 10k
                    if not index % (BATCH_SIZE * 100):
                        self.env.cr.commit()

        return participants

    def action_view_campaign_mailings(self):
        self.ensure_one()

        form_view_ref = self.env.ref('bhs_marketing_automation.bhs_marketing_campaign_mailing_view_mailing_form_inherit', False)
        action = self.env["ir.actions.actions"]._for_xml_id("bhs_marketing_automation.bhs_marketing_campaign_mailing_action")
        action.update({'views': [(form_view_ref.id, 'form')],
                       'res_id': self.id})

        return action

    @api.depends('marketing_activity_ids.mass_mailing_id', 'is_auto_campaign')
    def _compute_mass_mailing_ids(self):
        for campaign in self:
            if campaign.is_auto_campaign:
                campaign.mass_mailing_ids = [(6, 0, campaign.mapped('marketing_activity_ids.mass_mailing_id').filtered(lambda mailing: mailing.mailing_type == 'mail').ids)]
